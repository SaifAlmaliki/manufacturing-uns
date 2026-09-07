from uns_factory_agent.classify import classify


def test_job_cards_and_hi_map_to_kinds():
    assert classify("What is in alarm in my plant right now?") == "alarms_on_focus"
    assert classify("What is in alarm on the Asset I am looking at?") == "alarms_on_focus"
    assert classify("Has Pump P101 lost performance over the last three weeks?") == "performance_rca"
    assert classify("How does the selected metric (or this line's main metrics) compare to the last eight hours?") == "metric_vs_window"
    assert classify("How does this metric compare to the last eight hours?") == "metric_vs_window"
    assert classify("Which Assets on my plant path published in the last hour?") == "publishers_on_path"
    assert classify("Which Assets on this path published in the last hour?") == "publishers_on_path"
    assert classify("hi") == "plant_overview"
    assert classify("what's going on?") == "plant_overview"
    assert classify("how does historian work?") == "platform_map"
    assert classify("what is an Access Group?") == "platform_map"
    assert classify("why is GraphQL down?") == "platform_health"
    assert classify("Ack this alarm") == "other"
