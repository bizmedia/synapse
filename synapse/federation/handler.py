# -*- coding: utf-8 -*-

from twisted.internet import defer

from synapse.api.errors import AuthError

from .pdu_codec import PduCodec


class FederationEventHandler(object):

    def __init__(self, hs):
        self.persistence = hs.get_persistence_service()
        self.replication_layer = hs.get_replication_layer()
        self.state_handler = hs.get_state_handler()
        # self.auth_handler = gs.get_auth_handler()
        self.event_handler = (
            hs.get_event_handler_factory().federation_handler()
        )
        self.server_name = hs.hostname

        self.lock_manager = hs.get_room_lock_manager()

        self.replication_layer.set_handler(self)

        self.pdu_codec = PduCodec(hs)

    @defer.inlineCallbacks
    def handle_new_event(self, event):
        yield self._fill_out_prev_events(event)

        pdu = self.pdu_codec.pdu_from_event(event)

        pdu.destinations = yield self.persistence.get_servers_in_context(
            pdu.context
        )

        yield self.replication_layer.send_pdu(pdu)

    @defer.inlineCallbacks
    def backfill(self, room_id, limit):
        # TODO: Work out which destinations to ask for pagination
        # self.replication_layer.paginate(dest, room_id, limit)
        pass

    @defer.inlineCallbacks
    def on_receive_pdu(self, pdu):
        event = self.pdu_codec.event_from_pdu(pdu)

        try:
            with (yield self.lock_manager.lock(pdu.context)):
                # Auth is hard. Let's ignore it for now.
                # yield self.auth_handler.check(event)

                def _on_new_state(self, new_state_event):
                    return self._on_new_state(pdu, new_state_event)

                if event.is_state:
                    yield self.state_handler.handle_new_state(
                        event,
                        _on_new_state
                    )

                    # TODO: Do we want to inform people about state_events that
                    # result in a clobber?

                    return
                else:
                    yield self.event_handler.on_receive(event)

        except AuthError:
            # TODO: Implement something in federation that allows us to
            # respond to PDU.
            raise

        return

    @defer.inlineCallbacks
    def _on_new_state(self, pdu, new_state_event):
        # TODO: Do any persistence stuff here. Notifiy C2S about this new
        # state.

        yield self.persistence.update_current_state(
            pdu_id=pdu.pdu_id,
            origin=pdu.origin,
            context=pdu.context,
            pdu_type=pdu.pdu_type,
            state_key=pdu.state_key
        )

        yield self.event_handler.on_receive(new_state_event)

    @defer.inlineCallbacks
    def _fill_out_prev_events(self, event):
        if hasattr("prev_events", event):
            return

        results = yield self.service.get_latest_pdus_in_context(event.room_id)

        event.prev_events = [
            "%s@%s" % (p_id, origin) for p_id, origin, _ in results
        ]

        if results:
            event.depth = max([int(v) for _, _, v in results]) + 1
        else:
            event.depth = 0
