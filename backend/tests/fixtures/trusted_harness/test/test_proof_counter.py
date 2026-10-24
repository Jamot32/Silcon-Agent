from sa_tb import case, Reset, Cycle

@case(behaviors=('B1',), plans=('T1',), reset_case=True, edge_case=True, edge_inputs=('enable',))
def test_reset():
    yield Reset({'enable': 0}, {'q': 0})
    yield Cycle({'enable': 0}, before={'q': 0}, after={'q': 0})

@case(behaviors=('B1',), plans=('T2',), reset_case=True, edge_case=True, edge_inputs=('enable',))
def test_increment():
    yield Reset({'enable': 0}, {'q': 0})
    yield Cycle({'enable': 1}, before={'q': 0}, after={'q': 1})
    yield Cycle({'enable': 1}, before={'q': 1}, after={'q': 2})

@case(behaviors=('B1',), plans=('T3',), reset_case=True, edge_case=True, edge_inputs=('enable',))
def test_hold():
    yield Reset({'enable': 0}, {'q': 0})
    yield Cycle({'enable': 1}, before={'q': 0}, after={'q': 1})
    yield Cycle({'enable': 0}, before={'q': 1}, after={'q': 1})

@case(behaviors=('B1',), plans=('T4',), reset_case=True, edge_case=True, edge_inputs=('enable',))
def test_wrap():
    yield Reset({'enable': 0}, {'q': 0})
    for value in range(1, 18):
        yield Cycle({'enable': 1}, before={'q': (value - 1) & 15}, after={'q': value & 15})
