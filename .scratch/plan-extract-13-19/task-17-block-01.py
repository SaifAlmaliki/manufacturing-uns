EXPECTED_SIGNAL_COUNT = {
    "energy": {"EM-01": 17, "EM-02": 17, "TR-01": 6, "MCC-01": 6, "MCC-02": 6},
    "water": {"FM-01": 5, "DEMIN-01": 6, "CT-01": 11, "CT-02": 11, "EFF-01": 9},
    "utilities": {
        "CMP-01": 8,
        "CMP-02": 8,
        "CMP-03": 8,
        "DRY-01": 4,
        "AH-01": 4,
        "AH-02": 4,
        "BLR-01": 11,
        "SH-01": 3,
        "CR-01": 4,
        "N2-01": 5,
        "N2H-01": 2,
        "AHU-01": 8,
        "CH-01": 7,
    },
    "asset_health": {"VIB-01": 15, "VIB-02": 12},
}

EXPECTED_DEVICE_COUNT = {
    "energy": {"EM-01": 1, "EM-02": 1, "TR-01": 1, "MCC-01": 1, "MCC-02": 1},
    "water": {"FM-01": 2, "DEMIN-01": 1, "CT-01": 1, "CT-02": 1, "EFF-01": 1},
    "utilities": {
        "CMP-01": 1,
        "CMP-02": 1,
        "CMP-03": 1,
        "DRY-01": 1,
        "AH-01": 1,
        "AH-02": 1,
        "BLR-01": 1,
        "SH-01": 1,
        "CR-01": 1,
        "N2-01": 1,
        "N2H-01": 1,
        "AHU-01": 1,
        "CH-01": 1,
    },
    # VIB-01 lands on every Production cell: Dormagen Line1/Cell1, Line1/Cell2,
    # Line2/Cell1, and Krefeld Line1/Cell1. VIB-02 lands on the three compressor cells.
    "asset_health": {"VIB-01": 4, "VIB-02": 3},
}
