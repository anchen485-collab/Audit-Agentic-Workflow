from app.observability.trace import new_trace_id, run_with_trace


def test_new_trace_id_has_prefix():
    """trace_id 应该有固定前缀，方便日志检索。"""
    trace_id = new_trace_id()

    assert trace_id.startswith("trace_")
    assert len(trace_id) > len("trace_")


def test_run_with_trace_records_success_event():
    """成功执行函数时，应该返回结果和成功 trace 事件。"""

    def do_work():
        return {"value": 1}

    result, event = run_with_trace(
        trace_id="trace_test",
        node_name="test_node",
        func=do_work,
    )

    assert result == {"value": 1}
    assert event.trace_id == "trace_test"
    assert event.node_name == "test_node"
    assert event.status == "success"
    assert event.duration_ms >= 0