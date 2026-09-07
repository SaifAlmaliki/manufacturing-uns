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


def test_performance_rca_is_broader_than_lost_performance():
    assert classify("Is the pump degrading this month?") == "performance_rca"
    assert classify("This line's throughput has been declining over the past week.") == "performance_rca"
    assert classify("P101 has been running slower this week.") == "performance_rca"
    # A bare decline word with no time window is not enough — avoid over-triggering RCA
    # on every vague complaint.
    assert classify("This pump seems worse.") != "performance_rca"


def test_data_intents_win_over_platform_map_when_access_group_is_mentioned():
    assert classify("What is in alarm in my Access Group?") == "alarms_on_focus"
    assert classify("Has P101 lost performance in my Access Group over the last month?") == "performance_rca"


def test_platform_map_is_narrowed_to_literal_platform_questions():
    assert classify("What is an Access Group?") == "platform_map"
    assert classify("How does historian work?") == "platform_map"
    assert classify("What is this console?") == "platform_map"
    assert classify("Does my Access Group cover P101?") == "other"
