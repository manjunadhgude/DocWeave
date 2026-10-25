"""Verify an existing database matches DocWeave's current ORM schema.

Run this before `alembic stamp head` on an existing, unversioned database.
The command is read-only.
"""
import sys
from pathlib import Path

from sqlalchemy import inspect

# Allow this script to run directly from the repository's tools directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docweave.storage import Base, engine


def main() -> int:
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(Base.metadata.tables)

    problems = []
    if actual_tables != expected_tables:
        problems.append(
            f"Table mismatch: expected {sorted(expected_tables)}, "
            f"found {sorted(actual_tables)}"
        )

    for table_name in sorted(expected_tables & actual_tables):
        model_table = Base.metadata.tables[table_name]
        actual_columns = {
            column["name"]: column
            for column in inspector.get_columns(table_name)
        }
        expected_columns = {column.name: column for column in model_table.columns}

        if set(actual_columns) != set(expected_columns):
            problems.append(
                f"{table_name}: column mismatch; expected "
                f"{sorted(expected_columns)}, found {sorted(actual_columns)}"
            )
            continue

        for name, expected in expected_columns.items():
            actual = actual_columns[name]
            if actual["type"]._type_affinity != expected.type._type_affinity:
                problems.append(
                    f"{table_name}.{name}: type mismatch; expected "
                    f"{expected.type}, found {actual['type']}"
                )
            if isinstance(expected.type, __import__("sqlalchemy").String):
                if getattr(actual["type"], "length", None) != expected.type.length:
                    problems.append(
                        f"{table_name}.{name}: string length mismatch"
                    )
            if actual["nullable"] != expected.nullable:
                problems.append(
                    f"{table_name}.{name}: nullability mismatch"
                )

        expected_pk = sorted(column.name for column in model_table.primary_key.columns)
        actual_pk = sorted(
            inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        )
        if expected_pk != actual_pk:
            problems.append(f"{table_name}: primary-key mismatch")

        expected_indexes = {
            index.name: tuple(column.name for column in index.columns)
            for index in model_table.indexes
        }
        actual_unique_constraints = inspector.get_unique_constraints(table_name)
        unique_constraint_names = {
            constraint.get("name") for constraint in actual_unique_constraints
        }
        actual_indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
            if index["name"] not in unique_constraint_names
        }
        if expected_indexes != actual_indexes:
            problems.append(
                f"{table_name}: index mismatch; expected {expected_indexes}, "
                f"found {actual_indexes}"
            )

        expected_unique = {
            (
                constraint.name,
                tuple(sorted(column.name for column in constraint.columns)),
            )
            for constraint in model_table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        actual_unique = {
            (
                constraint.get("name"),
                tuple(sorted(constraint.get("column_names") or [])),
            )
            for constraint in actual_unique_constraints
        }
        if expected_unique != actual_unique:
            problems.append(
                f"{table_name}: unique-constraint mismatch; "
                f"expected {expected_unique}, found {actual_unique}"
            )

    if problems:
        print("SCHEMA VERIFICATION FAILED:")
        for problem in problems:
            print(f"- {problem}")
        print("Do not stamp this database. Investigate the differences first.")
        return 1

    print("Schema matches the current DocWeave ORM models.")
    print("No tables or records were modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
