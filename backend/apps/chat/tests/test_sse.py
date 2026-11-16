"""Reading the agent's event stream, and writing the SPA's."""

import json

from asgiref.sync import async_to_sync

from apps.chat import sse


def read(*chunks: str) -> list[tuple[str, str]]:
    async def collect():
        async def source():
            for chunk in chunks:
                yield chunk

        return [event async for event in sse.parse(source())]

    return async_to_sync(collect)()


def test_an_event_is_its_name_and_its_data():
    assert read('event: text\ndata: {"delta": "Hi"}\n\n') == [("text", '{"delta": "Hi"}')]


def test_an_event_split_across_chunks_comes_out_whole():
    # The network cuts where it likes, including inside a line ending.
    assert read("event: te", 'xt\ndata: {"delta"', ': "Hi"}\r', "\n\r\n") == [
        ("text", '{"delta": "Hi"}')
    ]


def test_crlf_line_endings_are_read():
    assert read("event: done\r\ndata: {}\r\n\r\n") == [("done", "{}")]


def test_comments_and_unknown_fields_are_read_past():
    stream = ": keep-alive\n\nid: 7\nretry: 1000\nevent: text\ndata: x\n\n"
    assert read(stream) == [("text", "x")]


def test_data_lines_join_with_newlines():
    assert read("data: one\ndata: two\n\n") == [("message", "one\ntwo")]


def test_an_event_with_no_data_is_not_an_event():
    assert read("event: text\n\n") == []


def test_a_last_event_the_stream_never_finished_is_dropped():
    # No blank line after it: it may have been cut short.
    assert read('event: text\ndata: {"delta": "Hi"}\n\nevent: done\ndata: {"te') == [
        ("text", '{"delta": "Hi"}')
    ]


def test_a_frame_carries_the_whole_event_as_one_json_line():
    framed = sse.frame({"event": "text", "delta": "two\nlines é"}).decode()

    head, data, end = framed.split("\n", 2)
    assert head == "event: text"
    assert json.loads(data.removeprefix("data: ")) == {"event": "text", "delta": "two\nlines é"}
    assert end == "\n"
