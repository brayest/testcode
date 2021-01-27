import functools
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Tuple, Optional

import werkzeug
from loguru import logger
from sqlalchemy import and_, func
from sqlalchemy.ext.hybrid import hybrid_method
from sqlalchemy.orm import backref

from server.api.database import db
from server.api.database.mixins import (
    Column,
    Model,
    SurrogatePK,
    reference_col,
    relationship,
)
from server.api.database.models import Appointment, LessonCreator, WorkDay
from server.api.rules import LessonRule, rules_registry
from server.api.utils import get_slots
from server.consts import WORKDAY_DATE_FORMAT


class Teacher(SurrogatePK, LessonCreator):
    """A teacher of the app."""

    __tablename__ = "teachers"
    price = Column(db.Integer, nullable=False)
    price_rating = Column(db.Float, nullable=True)
    availabillity_rating = Column(db.Float, nullable=True)
    content_rating = Column(db.Float, nullable=True)
    lesson_duration = Column(db.Integer, default=40, nullable=False)
    is_approved = Column(db.Boolean, default=False, nullable=False)  # admin approved
    invoice_api_key = Column(db.String(240), nullable=True)
    invoice_api_uid = Column(db.String(240), nullable=True)
    crn = Column(db.Integer, nullable=True)
    created_at = Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ALLOWED_FILTERS = ["price", "is_approved"]

    def __init__(self, **kwargs):
        """Create instance."""
        db.Model.__init__(self, **kwargs)

    def work_hours_for_date(self, date: datetime, student: "Student" = None):
        car = self.cars.first()
        if student:
            car = student.car
        work_hours = self.work_days.filter_by(on_date=date.date(), car=car).all()
        if not work_hours:
            weekday = ["NEVER USED", 1, 2, 3, 4, 5, 6, 0][
                date.isoweekday()
            ]  # converty sundays to 0
            work_hours = self.work_days.filter_by(day=weekday).all()
            logger.debug(f"No specific days found. Going with default")

        logger.debug(f"found these work days on the specific date: {work_hours}")
        return work_hours

    def taken_appointments_tuples(self, existing_query, only_approved: bool):
        """returns list with tuples of start and end hours of taken lessons"""
        and_partial = functools.partial(and_, Appointment.student_id != None)
        and_func = and_partial()
        if only_approved:
            and_func = and_partial(Appointment.is_approved == True)
        taken_appointments = existing_query.filter(and_func).all()
        return [
            (
                appointment.date,
                appointment.date + timedelta(minutes=appointment.duration),
            )
            for appointment in taken_appointments
        ]

    def available_hours(
        self,
        requested_date: datetime,
        student: "Student" = None,
        duration: int = None,
        only_approved: bool = False,
        places: Tuple[Optional[str]] = (None, None),
    ) -> Iterable[Tuple[datetime, datetime]]:
        """
        1. calculate available hours - decrease existing lessons times from work hours
        2. calculate lesson hours from available hours by default lesson duration
        MUST BE 24-hour format. 09:00, not 9:00
        """
        if not requested_date:
            return []

        todays_appointments = self.appointments.filter(
            func.extract("day", Appointment.date) == requested_date.day
        ).filter(func.extract("month", Appointment.date) == requested_date.month)
        work_hours = self.work_hours_for_date(requested_date, student=student)
        taken_appointments = self.taken_appointments_tuples(
            todays_appointments, only_approved
        )
        blacklist_hours = {"start_hour": set(), "end_hour": set()}
        if student and work_hours:
            approved_taken_appointments = self.taken_appointments_tuples(
                todays_appointments, only_approved=True
            )
            hours = LessonRule.init_hours(
                requested_date, student, work_hours, approved_taken_appointments
            )
            for rule_class in rules_registry:
                rule_instance: LessonRule = rule_class(
                    requested_date, student, hours, places
                )
                blacklisted = rule_instance.blacklisted()
                for key in blacklist_hours.keys():
                    blacklist_hours[key].update(blacklisted[key])

        work_hours.sort(key=lambda x: x.from_hour)  # sort from early to late
        for slot in work_hours:
            hours = (
                requested_date.replace(hour=slot.from_hour, minute=slot.from_minutes),
                requested_date.replace(hour=slot.to_hour, minute=slot.to_minutes),
            )
            yield from get_slots(
                hours,
                taken_appointments,
                timedelta(minutes=duration or self.lesson_duration),
                force_future=True,
                blacklist=blacklist_hours,
            )

    @hybrid_method
    def filter_work_days(self, args: werkzeug.datastructures.MultiDict):
        args = args.copy()
        if "on_date" not in args:
            args["on_date"] = None

        def custom_date_func(value):
            return datetime.strptime(value, WORKDAY_DATE_FORMAT).date()

        return WorkDay.filter_and_sort(
            args, query=self.work_days, custom_date=custom_date_func
        )

    def to_dict(self, with_user=True):
        return {
            "teacher_id": self.id,
            "price": self.price,
            "lesson_duration": self.lesson_duration,
            "price_rating": self.price_rating,
            "availabillity_rating": self.availabillity_rating,
            "content_rating": self.content_rating,
            "user": self.user.to_dict() if with_user else None,
            "is_approved": self.is_approved,
            "cars": [car.to_dict() for car in self.cars],
        }
