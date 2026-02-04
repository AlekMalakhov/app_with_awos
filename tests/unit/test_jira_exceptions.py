"""Unit tests for Jira exception hierarchy."""

import pytest

from src.jira.exceptions import (
    JiraAuthenticationError,
    JiraConnectionError,
    JiraError,
    JiraIssueTypeNotSupportedError,
    JiraTicketNotFoundError,
)


class TestJiraExceptionInheritance:
    """Test suite for verifying exception inheritance hierarchy."""

    def test_jira_error_is_subclass_of_exception(self):
        """Test that JiraError is a subclass of built-in Exception."""
        assert issubclass(JiraError, Exception)

    def test_jira_authentication_error_is_subclass_of_jira_error(self):
        """Test that JiraAuthenticationError is a subclass of JiraError."""
        assert issubclass(JiraAuthenticationError, JiraError)

    def test_jira_connection_error_is_subclass_of_jira_error(self):
        """Test that JiraConnectionError is a subclass of JiraError."""
        assert issubclass(JiraConnectionError, JiraError)

    def test_jira_ticket_not_found_error_is_subclass_of_jira_error(self):
        """Test that JiraTicketNotFoundError is a subclass of JiraError."""
        assert issubclass(JiraTicketNotFoundError, JiraError)

    def test_jira_issue_type_not_supported_error_is_subclass_of_jira_error(self):
        """Test that JiraIssueTypeNotSupportedError is a subclass of JiraError."""
        assert issubclass(JiraIssueTypeNotSupportedError, JiraError)


class TestJiraExceptionRaiseAndCatch:
    """Test suite for verifying exceptions can be raised and caught."""

    def test_jira_error_can_be_raised_with_message(self):
        """Test that JiraError can be raised with a custom message."""
        message = "A generic Jira error occurred"
        with pytest.raises(JiraError) as exc_info:
            raise JiraError(message)
        assert str(exc_info.value) == message

    def test_jira_authentication_error_can_be_raised_with_message(self):
        """Test that JiraAuthenticationError can be raised with a custom message."""
        message = "Invalid credentials provided"
        with pytest.raises(JiraAuthenticationError) as exc_info:
            raise JiraAuthenticationError(message)
        assert str(exc_info.value) == message

    def test_jira_connection_error_can_be_raised_with_message(self):
        """Test that JiraConnectionError can be raised with a custom message."""
        message = "Failed to connect to Jira after 3 retries"
        with pytest.raises(JiraConnectionError) as exc_info:
            raise JiraConnectionError(message)
        assert str(exc_info.value) == message

    def test_jira_ticket_not_found_error_can_be_raised_with_message(self):
        """Test that JiraTicketNotFoundError can be raised with a custom message."""
        message = "Ticket PROJ-123 not found"
        with pytest.raises(JiraTicketNotFoundError) as exc_info:
            raise JiraTicketNotFoundError(message)
        assert str(exc_info.value) == message

    def test_jira_issue_type_not_supported_error_can_be_raised_with_message(self):
        """Test that JiraIssueTypeNotSupportedError can be raised with a custom message."""
        message = "Issue type 'Epic' is not supported"
        with pytest.raises(JiraIssueTypeNotSupportedError) as exc_info:
            raise JiraIssueTypeNotSupportedError(message)
        assert str(exc_info.value) == message

    def test_catching_jira_error_catches_authentication_error(self):
        """Test that catching JiraError also catches JiraAuthenticationError."""
        with pytest.raises(JiraError):
            raise JiraAuthenticationError("Auth failed")

    def test_catching_jira_error_catches_connection_error(self):
        """Test that catching JiraError also catches JiraConnectionError."""
        with pytest.raises(JiraError):
            raise JiraConnectionError("Connection failed")

    def test_catching_jira_error_catches_ticket_not_found_error(self):
        """Test that catching JiraError also catches JiraTicketNotFoundError."""
        with pytest.raises(JiraError):
            raise JiraTicketNotFoundError("Ticket not found")

    def test_catching_jira_error_catches_issue_type_not_supported_error(self):
        """Test that catching JiraError also catches JiraIssueTypeNotSupportedError."""
        with pytest.raises(JiraError):
            raise JiraIssueTypeNotSupportedError("Issue type not supported")


class TestJiraExceptionInstantiation:
    """Test suite for verifying exception instantiation and message access."""

    def test_jira_error_message_accessible_via_str(self):
        """Test that JiraError message is accessible via str()."""
        message = "Test error message"
        error = JiraError(message)
        assert str(error) == message

    def test_jira_error_message_accessible_via_args(self):
        """Test that JiraError message is accessible via args[0]."""
        message = "Test error message"
        error = JiraError(message)
        assert error.args[0] == message

    def test_jira_authentication_error_message_accessible_via_str(self):
        """Test that JiraAuthenticationError message is accessible via str()."""
        message = "Authentication failed"
        error = JiraAuthenticationError(message)
        assert str(error) == message

    def test_jira_authentication_error_message_accessible_via_args(self):
        """Test that JiraAuthenticationError message is accessible via args[0]."""
        message = "Authentication failed"
        error = JiraAuthenticationError(message)
        assert error.args[0] == message

    def test_jira_connection_error_message_accessible_via_str(self):
        """Test that JiraConnectionError message is accessible via str()."""
        message = "Connection timeout"
        error = JiraConnectionError(message)
        assert str(error) == message

    def test_jira_connection_error_message_accessible_via_args(self):
        """Test that JiraConnectionError message is accessible via args[0]."""
        message = "Connection timeout"
        error = JiraConnectionError(message)
        assert error.args[0] == message

    def test_jira_ticket_not_found_error_message_accessible_via_str(self):
        """Test that JiraTicketNotFoundError message is accessible via str()."""
        message = "Ticket PROJ-456 does not exist"
        error = JiraTicketNotFoundError(message)
        assert str(error) == message

    def test_jira_ticket_not_found_error_message_accessible_via_args(self):
        """Test that JiraTicketNotFoundError message is accessible via args[0]."""
        message = "Ticket PROJ-456 does not exist"
        error = JiraTicketNotFoundError(message)
        assert error.args[0] == message

    def test_jira_issue_type_not_supported_error_message_accessible_via_str(self):
        """Test that JiraIssueTypeNotSupportedError message is accessible via str()."""
        message = "Issue type 'Sub-task' not in allowed list"
        error = JiraIssueTypeNotSupportedError(message)
        assert str(error) == message

    def test_jira_issue_type_not_supported_error_message_accessible_via_args(self):
        """Test that JiraIssueTypeNotSupportedError message is accessible via args[0]."""
        message = "Issue type 'Sub-task' not in allowed list"
        error = JiraIssueTypeNotSupportedError(message)
        assert error.args[0] == message

    def test_jira_error_instance_is_instance_of_exception(self):
        """Test that a JiraError instance is an instance of Exception."""
        error = JiraError("Test")
        assert isinstance(error, Exception)

    def test_jira_authentication_error_instance_is_instance_of_jira_error(self):
        """Test that a JiraAuthenticationError instance is an instance of JiraError."""
        error = JiraAuthenticationError("Test")
        assert isinstance(error, JiraError)

    def test_jira_connection_error_instance_is_instance_of_jira_error(self):
        """Test that a JiraConnectionError instance is an instance of JiraError."""
        error = JiraConnectionError("Test")
        assert isinstance(error, JiraError)

    def test_jira_ticket_not_found_error_instance_is_instance_of_jira_error(self):
        """Test that a JiraTicketNotFoundError instance is an instance of JiraError."""
        error = JiraTicketNotFoundError("Test")
        assert isinstance(error, JiraError)

    def test_jira_issue_type_not_supported_error_instance_is_instance_of_jira_error(self):
        """Test that a JiraIssueTypeNotSupportedError instance is an instance of JiraError."""
        error = JiraIssueTypeNotSupportedError("Test")
        assert isinstance(error, JiraError)
