# Backend Tests

This directory contains unit tests for the backend components.

## Running Tests

### Install pytest (if not already installed)

```bash
cd backend
pip install pytest pytest-mock
```

### Run all tests

```bash
cd backend/tests
pytest
```

### Run specific test file

```bash
pytest test_error_handling.py
```

### Run specific test class

```bash
pytest test_error_handling.py::TestHandleFailedToApply
```

### Run specific test

```bash
pytest test_error_handling.py::TestHandleFailedToApply::test_full_error_handling_flow
```

### Run with verbose output

```bash
pytest -v
```

### Run with coverage

```bash
pip install pytest-cov
pytest --cov=../linkedin_bot/actions --cov-report=html
```

## Test Files

- `test_error_handling.py` - Tests for error handling methods in StartHuntingAction
  - Screenshot capture and upload
  - Mixpanel event tracking
  - Slack notifications
  - Complete error handling flow
