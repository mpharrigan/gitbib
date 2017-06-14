# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.orm.exc import NoResultFound
from contextlib import contextmanager

from sqlalchemy.types import TypeDecorator, VARCHAR
import json


class JSONB(TypeDecorator):
    impl = VARCHAR

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(VARCHAR())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            return value
        return json.loads(value)


log = logging.getLogger(__name__)
Base = declarative_base()
Session = sessionmaker()


class SchemaVersion(Base):
    __tablename__ = 'versions'
    tableversion = 1

    id = Column(Integer, primary_key=True)
    table = Column(String)
    version = Column(Integer)

    @classmethod
    def update_schema(cls, prev, engine):
        pass


class Crossref(Base):
    __tablename__ = 'crossref'
    tableversion = 1

    doi = Column(String, primary_key=True)
    data = Column(JSONB)

    @classmethod
    def update_schema(cls, prev, engine):
        pass


class Arxiv(Base):
    __tablename__ = 'arxiv'
    tableversion = 1

    arxivid = Column(String, primary_key=True)
    data = Column(JSONB)

    @classmethod
    def update_schema(cls, prev, engine):
        pass


class Cache:
    tables = [
        SchemaVersion,
        Crossref,
        Arxiv,
    ]

    def __init__(self, connect):
        engine = create_engine(connect, echo=False)
        Session.configure(bind=engine)

        # The following checks for existence
        Base.metadata.create_all(engine)

        startup_sess = Session()
        self.handle_versioning(startup_sess, engine)
        startup_sess.commit()

    @contextmanager
    def scoped_session(self):
        """Provide a transactional scope around a series of operations."""
        session = Session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()

    def handle_versioning(self, session, engine):
        for table in self.tables:
            try:
                entry = (session.query(SchemaVersion)
                         .filter(SchemaVersion.table == table.__tablename__)
                         .one())
                if entry.version != table.tableversion:
                    log.warning("Updating {} from version {} to {}".format(table, entry.version, table.tableversion))
                    table.update_schema(prev=entry.version, engine=engine)
                    entry.version = table.tableversion
            except NoResultFound:
                session.add(
                    SchemaVersion(table=table.__tablename__,
                                  version=table.tableversion)
                )
