"""Test multi-user support in the database layer."""
import sqlite3
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from db.schema import init_db, get_connection
from db.queries import (
    NewTransaction,
    insert_transaction,
    get_pending_transactions,
    get_transaction_by_id,
    mark_email_processed,
    is_email_processed,
)


def test_multi_user_isolation():
    """Verify that two users have isolated transaction and email processing data."""
    # Create a temporary database for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Initialize the database
        init_db(db_path)
        conn = get_connection(db_path)

        try:
            # Create transactions for two users
            alice_txn = NewTransaction(
                user_id="alice",
                email_message_id="msg-001",
                amount=1000.0,
                date="2026-05-10",
                transaction_type="expense",
                merchant="Coffee Shop",
                bucket="fun",
                review_status="pending_review",
            )

            bob_txn = NewTransaction(
                user_id="bob",
                email_message_id="msg-001",  # Same message ID as Alice
                amount=2000.0,
                date="2026-05-10",
                transaction_type="expense",
                merchant="Grocery Store",
                bucket="fundamentals",
                review_status="pending_review",
            )

            alice_id = insert_transaction(conn, alice_txn)
            bob_id = insert_transaction(conn, bob_txn)
            print(f"✓ Inserted Alice's transaction (ID: {alice_id})")
            print(f"✓ Inserted Bob's transaction (ID: {bob_id})")

            # Test 1: Each user only sees their own transactions
            alice_pending = get_pending_transactions(conn, "alice")
            bob_pending = get_pending_transactions(conn, "bob")

            assert len(alice_pending) == 1, f"Expected 1 pending transaction for Alice, got {len(alice_pending)}"
            assert len(bob_pending) == 1, f"Expected 1 pending transaction for Bob, got {len(bob_pending)}"
            assert alice_pending[0].merchant == "Coffee Shop"
            assert bob_pending[0].merchant == "Grocery Store"
            print("✓ Each user sees only their own transactions")

            # Test 2: get_transaction_by_id is user-scoped
            alice_txn_check = get_transaction_by_id(conn, "alice", alice_id)
            bob_txn_check = get_transaction_by_id(conn, "bob", alice_id)  # Try to get Alice's txn as Bob

            assert alice_txn_check is not None, "Alice should see her own transaction"
            assert bob_txn_check is None, "Bob should NOT see Alice's transaction"
            print("✓ get_transaction_by_id respects user isolation")

            # Test 3: Email processing is user-scoped
            mark_email_processed(conn, "alice", "msg-001")

            assert is_email_processed(conn, "alice", "msg-001"), "Alice's email should be marked processed"
            assert not is_email_processed(conn, "bob", "msg-001"), "Bob's same message should NOT be marked processed"
            print("✓ Email processing is per-user")

            # Test 4: Composite unique constraint allows same message ID for different users
            try:
                duplicate_alice = NewTransaction(
                    user_id="alice",
                    email_message_id="msg-001",  # Duplicate for Alice
                    amount=500.0,
                    date="2026-05-11",
                    transaction_type="expense",
                )
                insert_transaction(conn, duplicate_alice)
                assert False, "Should have raised UNIQUE constraint error"
            except sqlite3.IntegrityError:
                print("✓ Composite UNIQUE(user_id, email_message_id) prevents duplicates per user")

            print("\n✅ All multi-user isolation tests passed!")

        finally:
            conn.close()


if __name__ == "__main__":
    test_multi_user_isolation()
