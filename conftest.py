def pytest_configure(config):
    config.addinivalue_line("markers", "live: hits live OpenHands/workbench services")
