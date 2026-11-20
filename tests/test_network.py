from island import network


def test_popup_texts():
    assert network.network_popup(None, (True, "Home")) is None
    assert network.network_popup((False, None), (True, "Home")) == ("Connected", "Home")
    assert network.network_popup((True, "Home"), (False, None)) == ("Disconnected", "No internet")
    assert network.network_popup((True, "Home"), (True, "Office")) == ("Connected", "Office")
    assert network.network_popup((True, "Home"), (True, "Home")) is None
    assert network.network_popup((False, None), (False, None)) is None


def test_live_state():
    online, name = network.network_state()
    assert isinstance(online, bool) and (name is None or isinstance(name, str))
