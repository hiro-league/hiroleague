"""A chat message's story hop by hop: the device's id names it, each hop is a timed step, and the frame's metadata
carries the step on to the next process."""

from hiro_commons.logging_foundation import story

from hiro_channel_sdk import message_story

MESSAGE_ID = "6f1c2a3b-4d5e-4f60-8a71-92b3c4d5e6f7"


def test_the_first_hop_starts_the_story_from_the_messages_own_id_and_carries_it_on():
    metadata: dict = {}
    with message_story.hop("gateway.relay", metadata, MESSAGE_ID, area="RELAY", line=False) as relay:
        assert relay.story_id == MESSAGE_ID.replace("-", "")
    assert metadata["traceparent"] == relay.carry()


def test_the_next_hop_continues_the_carried_step():
    metadata: dict = {}
    with message_story.hop("gateway.relay", metadata, MESSAGE_ID, area="RELAY", line=False) as relay:
        pass
    with message_story.hop("devices.receive", metadata, MESSAGE_ID, area="DEVICES", line=False) as receive:
        assert receive.story_id == relay.story_id and receive._parent_id == int(relay.step_id, 16)
    assert metadata["traceparent"] == receive.carry()  # the plugin's step goes on to the server


def test_a_reply_continues_its_messages_story_from_its_metadata():
    with story.begin("agent.run", story_id=story.id_for(MESSAGE_ID), line=False) as run:
        reply_metadata = story.inject({"hiro_reply_to_msg_id": MESSAGE_ID})
    with message_story.hop("server.send", reply_metadata, MESSAGE_ID, area="OUTBOUND", line=False) as send:
        assert send.story_id == run.story_id and send._parent_id == int(run.step_id, 16)


def test_a_frame_of_no_messages_story_gets_no_step():
    metadata: dict = {}
    with message_story.hop("server.receive", metadata, None, area="CHANNEL_MAN") as step:
        assert step is None and story.current() is None
    assert metadata == {}
