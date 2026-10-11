# Database migrations

Alembic is included in the dependency set. The current demo creates tables automatically so a fresh pitch environment starts without migration friction.

For institutional deployment, disable `Base.metadata.create_all()` and run versioned Alembic migrations after the target database and interoperability contracts are approved.
