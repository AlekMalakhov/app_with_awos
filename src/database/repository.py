"""Repository pattern implementation for conversation state persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from src.database.config import DatabaseSettings
from src.database.connection import get_database_connection
from src.database.models import (
    ConversationState,
    ConversationStatus,
    EscalationRecord,
    MessageRecord,
)


class ConversationRepository:
    """Repository for CRUD operations on conversation state.

    Provides methods for creating, reading, updating, and deleting
    conversation records in the SQLite database.
    """

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        settings: DatabaseSettings | None = None,
    ) -> None:
        """Initialize the repository with a database connection.

        Args:
            conn: Optional SQLite connection. If None, creates a new connection.
            settings: Optional DatabaseSettings. Used only if conn is None.
        """
        if conn is not None:
            self._conn = conn
            self._owns_connection = False
        else:
            self._conn = get_database_connection(settings)
            self._owns_connection = True

    def close(self) -> None:
        """Close the database connection if owned by this repository."""
        if self._owns_connection:
            self._conn.close()

    def create(self, conversation: ConversationState) -> ConversationState:
        """Create a new conversation record in the database.

        Args:
            conversation: ConversationState to persist.

        Returns:
            The persisted ConversationState with timestamps set.
        """
        now = datetime.now(UTC).isoformat()
        conversation_dict = conversation.model_dump()
        conversation_dict["created_at"] = now
        conversation_dict["updated_at"] = now

        # Serialize JSON fields
        existing_acs_json = (
            json.dumps(conversation_dict["existing_acs"])
            if conversation_dict["existing_acs"] is not None
            else None
        )
        proposed_acs_json = (
            json.dumps(conversation_dict["proposed_acs"])
            if conversation_dict["proposed_acs"] is not None
            else None
        )
        description_adf_json = (
            json.dumps(conversation_dict["description_adf"])
            if conversation_dict["description_adf"] is not None
            else None
        )
        message_history_json = json.dumps(
            [msg if isinstance(msg, dict) else msg.model_dump()
             for msg in conversation_dict["message_history"]]
        )

        self._conn.execute(
            """
            INSERT INTO conversations (
                id, slack_user_id, slack_channel_id, jira_ticket_key,
                status, existing_acs, proposed_acs, description_adf,
                error_message, slack_thread_ts, message_history,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_dict["id"],
                conversation_dict["slack_user_id"],
                conversation_dict["slack_channel_id"],
                conversation_dict["jira_ticket_key"],
                conversation_dict["status"],
                existing_acs_json,
                proposed_acs_json,
                description_adf_json,
                conversation_dict["error_message"],
                conversation_dict["slack_thread_ts"],
                message_history_json,
                conversation_dict["created_at"],
                conversation_dict["updated_at"],
            ),
        )
        self._conn.commit()

        # Return the persisted conversation with updated timestamps
        return ConversationState(
            id=conversation_dict["id"],
            slack_user_id=conversation_dict["slack_user_id"],
            slack_channel_id=conversation_dict["slack_channel_id"],
            jira_ticket_key=conversation_dict["jira_ticket_key"],
            status=conversation_dict["status"],
            existing_acs=conversation_dict["existing_acs"],
            proposed_acs=conversation_dict["proposed_acs"],
            description_adf=conversation_dict["description_adf"],
            error_message=conversation_dict["error_message"],
            slack_thread_ts=conversation_dict["slack_thread_ts"],
            message_history=[
                MessageRecord(**msg) if isinstance(msg, dict) else msg
                for msg in conversation_dict["message_history"]
            ],
            created_at=conversation_dict["created_at"],
            updated_at=conversation_dict["updated_at"],
        )

    def get_by_id(self, id: str) -> ConversationState | None:
        """Retrieve a conversation by its ID.

        Args:
            id: The UUID of the conversation to retrieve.

        Returns:
            ConversationState if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_conversation(row)

    def get_active(
        self, slack_user_id: str, slack_channel_id: str
    ) -> ConversationState | None:
        """Find an active (non-completed/cancelled) conversation.

        Args:
            slack_user_id: The Slack user ID.
            slack_channel_id: The Slack channel/DM ID.

        Returns:
            The active ConversationState if found, None otherwise.
        """
        terminal_statuses = (
            ConversationStatus.COMPLETED.value,
            ConversationStatus.CANCELLED.value,
            ConversationStatus.ERROR.value,
        )

        cursor = self._conn.execute(
            """
            SELECT * FROM conversations
            WHERE slack_user_id = ?
              AND slack_channel_id = ?
              AND status NOT IN (?, ?, ?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (slack_user_id, slack_channel_id, *terminal_statuses),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_conversation(row)

    def get_by_thread_ts(
        self, slack_channel_id: str, slack_thread_ts: str
    ) -> ConversationState | None:
        """Find a conversation by its Slack thread timestamp.

        Used to match incoming thread replies to existing conversations
        (e.g., escalation threads).

        Args:
            slack_channel_id: The Slack channel/DM ID.
            slack_thread_ts: The Slack thread root timestamp.

        Returns:
            The matching ConversationState if found, None otherwise.
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM conversations
            WHERE slack_channel_id = ?
              AND slack_thread_ts = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (slack_channel_id, slack_thread_ts),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_conversation(row)

    def update(self, conversation: ConversationState) -> ConversationState:
        """Update an existing conversation record.

        Args:
            conversation: ConversationState with updated fields.

        Returns:
            The updated ConversationState with new updated_at timestamp.
        """
        now = datetime.now(UTC).isoformat()
        conversation_dict = conversation.model_dump()
        conversation_dict["updated_at"] = now

        # Serialize JSON fields
        existing_acs_json = (
            json.dumps(conversation_dict["existing_acs"])
            if conversation_dict["existing_acs"] is not None
            else None
        )
        proposed_acs_json = (
            json.dumps(conversation_dict["proposed_acs"])
            if conversation_dict["proposed_acs"] is not None
            else None
        )
        description_adf_json = (
            json.dumps(conversation_dict["description_adf"])
            if conversation_dict["description_adf"] is not None
            else None
        )
        message_history_json = json.dumps(
            [msg if isinstance(msg, dict) else msg.model_dump()
             for msg in conversation_dict["message_history"]]
        )

        self._conn.execute(
            """
            UPDATE conversations SET
                slack_user_id = ?,
                slack_channel_id = ?,
                jira_ticket_key = ?,
                status = ?,
                existing_acs = ?,
                proposed_acs = ?,
                description_adf = ?,
                error_message = ?,
                slack_thread_ts = ?,
                message_history = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                conversation_dict["slack_user_id"],
                conversation_dict["slack_channel_id"],
                conversation_dict["jira_ticket_key"],
                conversation_dict["status"],
                existing_acs_json,
                proposed_acs_json,
                description_adf_json,
                conversation_dict["error_message"],
                conversation_dict["slack_thread_ts"],
                message_history_json,
                conversation_dict["updated_at"],
                conversation_dict["id"],
            ),
        )
        self._conn.commit()

        # Return the updated conversation
        return ConversationState(
            id=conversation_dict["id"],
            slack_user_id=conversation_dict["slack_user_id"],
            slack_channel_id=conversation_dict["slack_channel_id"],
            jira_ticket_key=conversation_dict["jira_ticket_key"],
            status=conversation_dict["status"],
            existing_acs=conversation_dict["existing_acs"],
            proposed_acs=conversation_dict["proposed_acs"],
            description_adf=conversation_dict["description_adf"],
            error_message=conversation_dict["error_message"],
            slack_thread_ts=conversation_dict["slack_thread_ts"],
            message_history=[
                MessageRecord(**msg) if isinstance(msg, dict) else msg
                for msg in conversation_dict["message_history"]
            ],
            created_at=conversation_dict["created_at"],
            updated_at=conversation_dict["updated_at"],
        )

    def delete(self, id: str) -> bool:
        """Delete a conversation by its ID.

        Args:
            id: The UUID of the conversation to delete.

        Returns:
            True if a record was deleted, False if no record found.
        """
        cursor = self._conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (id,),
        )
        self._conn.commit()

        return cursor.rowcount > 0

    def delete_stale(self, older_than_days: int = 7) -> int:
        """Delete conversations in terminal states older than the threshold.

        Removes conversations with status COMPLETED, CANCELLED, or ERROR
        whose updated_at timestamp is older than the specified number of days.

        Args:
            older_than_days: Age threshold in days. Conversations with
                updated_at older than this many days ago will be deleted.

        Returns:
            The number of conversations deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        terminal_statuses = (
            ConversationStatus.COMPLETED.value,
            ConversationStatus.CANCELLED.value,
            ConversationStatus.ERROR.value,
        )

        cursor = self._conn.execute(
            """
            DELETE FROM conversations
            WHERE status IN (?, ?, ?)
              AND updated_at < ?
            """,
            (*terminal_statuses, cutoff),
        )
        self._conn.commit()

        return cursor.rowcount

    def delete_abandoned(self, older_than_days: int = 7) -> int:
        """Delete conversations stuck in non-terminal states older than the threshold.

        Removes conversations with status AWAITING_TICKET, FETCHING_TICKET,
        GENERATING_ACS, COMPARING, AWAITING_APPROVAL, PROCESSING_MODIFICATION,
        or WRITING_TO_JIRA whose updated_at timestamp is older than the
        specified number of days.

        Args:
            older_than_days: Age threshold in days. Conversations with
                updated_at older than this many days ago will be deleted.

        Returns:
            The number of conversations deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        non_terminal_statuses = (
            ConversationStatus.AWAITING_TICKET.value,
            ConversationStatus.FETCHING_TICKET.value,
            ConversationStatus.GENERATING_ACS.value,
            ConversationStatus.COMPARING.value,
            ConversationStatus.AWAITING_APPROVAL.value,
            ConversationStatus.PROCESSING_MODIFICATION.value,
            ConversationStatus.WRITING_TO_JIRA.value,
        )

        cursor = self._conn.execute(
            """
            DELETE FROM conversations
            WHERE status IN (?, ?, ?, ?, ?, ?, ?)
              AND updated_at < ?
            """,
            (*non_terminal_statuses, cutoff),
        )
        self._conn.commit()

        return cursor.rowcount

    def _row_to_conversation(self, row: sqlite3.Row) -> ConversationState:
        """Convert a database row to a ConversationState model.

        Args:
            row: SQLite row object.

        Returns:
            ConversationState instance.
        """
        # Parse JSON fields
        existing_acs = (
            json.loads(row["existing_acs"]) if row["existing_acs"] else None
        )
        proposed_acs = (
            json.loads(row["proposed_acs"]) if row["proposed_acs"] else None
        )
        # Handle description_adf column which may not exist in older databases
        description_adf = None
        try:
            if row["description_adf"]:
                description_adf = json.loads(row["description_adf"])
        except (IndexError, KeyError):
            # Column doesn't exist in this database version
            pass

        # Handle error_message column which may not exist in older databases
        error_message = None
        try:
            error_message = row["error_message"]
        except (IndexError, KeyError):
            # Column doesn't exist in this database version
            pass

        # Handle slack_thread_ts column which may not exist in older databases
        slack_thread_ts = None
        try:
            slack_thread_ts = row["slack_thread_ts"]
        except (IndexError, KeyError):
            pass

        message_history_raw = json.loads(row["message_history"])
        message_history = [MessageRecord(**msg) for msg in message_history_raw]

        return ConversationState(
            id=row["id"],
            slack_user_id=row["slack_user_id"],
            slack_channel_id=row["slack_channel_id"],
            jira_ticket_key=row["jira_ticket_key"],
            status=ConversationStatus(row["status"]),
            existing_acs=existing_acs,
            proposed_acs=proposed_acs,
            description_adf=description_adf,
            error_message=error_message,
            slack_thread_ts=slack_thread_ts,
            message_history=message_history,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class EscalationRepository:
    """Repository for CRUD operations on escalation records.

    Provides methods for creating and querying escalation records
    in the SQLite database.
    """

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        settings: DatabaseSettings | None = None,
    ) -> None:
        """Initialize the repository with a database connection.

        Args:
            conn: Optional SQLite connection. If None, creates a new connection.
            settings: Optional DatabaseSettings. Used only if conn is None.
        """
        if conn is not None:
            self._conn = conn
            self._owns_connection = False
        else:
            self._conn = get_database_connection(settings)
            self._owns_connection = True

    def close(self) -> None:
        """Close the database connection if owned by this repository."""
        if self._owns_connection:
            self._conn.close()

    def create(self, record: EscalationRecord) -> None:
        """Insert a new escalation record into the database.

        The confidence_gaps list is serialized to a JSON string for storage.

        Args:
            record: EscalationRecord to persist.
        """
        confidence_gaps_json = json.dumps(record.confidence_gaps)

        self._conn.execute(
            """
            INSERT INTO escalations (
                id, jira_ticket_key, confidence_score, confidence_gaps,
                slack_user_id, status, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.jira_ticket_key,
                record.confidence_score,
                confidence_gaps_json,
                record.slack_user_id,
                record.status,
                record.error_message,
                record.created_at,
            ),
        )
        self._conn.commit()

    def get_by_ticket_key(self, ticket_key: str) -> list[EscalationRecord]:
        """Retrieve all escalation records for a given Jira ticket key.

        The confidence_gaps field is deserialized from its JSON string
        representation back into a list of strings.

        Args:
            ticket_key: The Jira ticket key (e.g., "PROJ-123").

        Returns:
            List of EscalationRecord instances, possibly empty.
        """
        cursor = self._conn.execute(
            "SELECT * FROM escalations WHERE jira_ticket_key = ?",
            (ticket_key,),
        )
        rows = cursor.fetchall()

        return [self._row_to_escalation(row) for row in rows]

    def _row_to_escalation(self, row: sqlite3.Row) -> EscalationRecord:
        """Convert a database row to an EscalationRecord model.

        Args:
            row: SQLite row object.

        Returns:
            EscalationRecord instance.
        """
        confidence_gaps = json.loads(row["confidence_gaps"])

        return EscalationRecord(
            id=row["id"],
            jira_ticket_key=row["jira_ticket_key"],
            confidence_score=row["confidence_score"],
            confidence_gaps=confidence_gaps,
            slack_user_id=row["slack_user_id"],
            status=row["status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
