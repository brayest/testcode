from datetime import datetime, timedelta

import pytest
from loguru import logger

from server.api.blueprints.appointments import get_data, handle_places
from server.api.database.models import (
    Appointment,
    AppointmentType,
    Payment,
    Place,
    Student,
    Topic,
    WorkDay,
    LessonTopic,
    Car,
)
from server.consts import DATE_FORMAT
from server.error_handling import RouteError
from dateutil import relativedelta

tomorrow = datetime.utcnow() + timedelta(days=1)


def create_lesson(
    teacher,
    student,
    meetup,
    dropoff,
    date,
    duration=40,
    deleted=False,
    is_approved=True,
    **kwargs,
):
    return Appointment.create(
        teacher=teacher,
        student=student,
        creator=student.user if student else teacher.user,
        duration=duration,
        date=date.replace(second=0, microsecond=0),
        meetup_place=meetup,
        dropoff_place=dropoff,
        deleted=deleted,
        is_approved=is_approved,
        **kwargs,
    )


def test_lessons(auth, teacher, student, meetup, dropoff, requester):
    date = datetime(year=2018, month=11, day=27, hour=13, minute=00)
    create_lesson(teacher, student, meetup, dropoff, date)
    create_lesson(teacher, student, meetup, dropoff, date, deleted=True)
    auth.login(email=student.user.email)
    resp1 = requester.get("/appointments/?limit=1&page=1")  # no filters
    assert isinstance(resp1.json["data"], list)
    assert resp1.json["next_url"]
    resp2 = requester.get(resp1.json["next_url"])
    assert resp2.json["data"][0]["id"] != resp1.json["data"][0]["id"]
    resp = requester.get("/appointments/?student_id=gt:1")
    assert not resp.json["data"]
    resp = requester.get("/appointments/?date=2018-20-01T20")
    assert "wrong parameters" in resp.json["message"].lower()
    resp = requester.get("/appointments/?deleted=true")
    assert len(resp.json["data"]) == 2


def test_deleted_lessons(auth, teacher, student, meetup, dropoff, requester):
    date = datetime(year=2018, month=11, day=27, hour=13, minute=00)
    create_lesson(teacher, student, meetup, dropoff, date, duration=80, deleted=True)
    auth.login(email=teacher.user.email)
    resp = requester.get("/appointments/?deleted=true")
    assert resp.json["data"][0]["duration"] == 80


def test_single_lesson(auth, teacher, student, meetup, dropoff, requester):
    date = datetime(year=2018, month=11, day=27, hour=13, minute=00)
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    auth.login(email=student.user.email)
    resp = requester.get(f"/appointments/{lesson.id}")
    assert resp.json["data"]
    auth.logout()
    auth.login()
    resp = requester.get(f"/appointments/{lesson.id}")
    assert resp._status_code == 401


def test_student_new_lesson(auth, teacher, student, requester, topic):
    auth.login(email=student.user.email)
    date = (tomorrow.replace(hour=16, minute=00)).strftime(DATE_FORMAT)
    kwargs = {
        "teacher": teacher,
        "day": 1,
        "from_hour": 7,
        "from_minutes": 0,
        "to_hour": 21,
        "to_minutes": 59,
        "on_date": tomorrow.date(),
    }
    WorkDay.create(**kwargs)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date,
            "duration": "60",
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
        },
    )
    assert not resp.json["data"]["is_approved"]
    assert resp.json["data"]["price"] == student.price * 1.5
    assert resp.json["data"]["duration"] == teacher.lesson_duration * 1.5


def test_student_different_car_new_lesson(auth, teacher, student, requester, topic):
    auth.login(email=student.user.email)
    date = (tomorrow.replace(hour=16, minute=00)).strftime(DATE_FORMAT)
    kwargs = {
        "teacher": teacher,
        "day": 1,
        "from_hour": 7,
        "from_minutes": 0,
        "to_hour": 21,
        "to_minutes": 59,
        "on_date": tomorrow.date(),
        "car": Car.create(teacher=teacher, number="11111111"),
    }
    WorkDay.create(**kwargs)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date,
            "duration": "60",
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
        },
    )
    assert "not available" in resp.json["message"]


def test_update_topics(auth, teacher, student, requester, topic):
    auth.login(email=teacher.user.email)
    date = (tomorrow.replace(hour=13, minute=00)).strftime(DATE_FORMAT)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date,
            "duration": 60,
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
        },
    )
    lesson_id = resp.json["data"]["id"]
    resp = requester.post(
        f"/appointments/{lesson_id}/topics",
        json={"topics": {"progress": [], "finished": [topic.id]}},
    )
    assert resp.json["data"]
    assert len(LessonTopic.query.all()) == 1

    another_topic = Topic.create(
        title="test3", min_lesson_number=20, max_lesson_number=22
    )
    # let's say we're editing a lesson, and sending existing topics
    resp = requester.post(
        f"/appointments/{lesson_id}/topics",
        json={"topics": {"progress": [another_topic.id], "finished": []}},
    )
    assert resp.json["data"]
    assert LessonTopic.query.filter_by(topic=another_topic).first()
    # now we're marking a finished topic
    resp = requester.post(
        f"/appointments/{lesson_id}/topics",
        json={"topics": {"progress": [], "finished": [another_topic.id]}},
    )
    assert resp.json["data"]
    assert (
        LessonTopic.query.filter_by(topic=another_topic)
        .order_by(LessonTopic.created_at.desc())
        .first()
        .is_finished
    )


@pytest.mark.parametrize(
    ("student_id", "topics", "error"),
    (
        (None, {}, "Lesson must have a student assigned."),
        (1, {"progress": [5]}, "Topic does not exist."),
    ),
)
def test_invalid_update_topics(
    auth, meetup, dropoff, teacher, requester, topic, student_id, topics, error
):
    auth.login(email=teacher.user.email)
    date = tomorrow.replace(hour=13, minute=00)
    student = Student.get_by_id(student_id) if student_id else None
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    resp = requester.post(f"/appointments/{lesson.id}/topics", json={"topics": topics})
    assert resp.status_code == 400
    assert resp.json["message"] == error


def test_hour_not_available(auth, teacher, student, requester):
    auth.login(email=student.user.email)
    date = (tomorrow.replace(hour=12, minute=00)).strftime(DATE_FORMAT)
    kwargs = {
        "teacher": teacher,
        "day": 1,
        "from_hour": 13,
        "from_minutes": 0,
        "to_hour": 17,
        "to_minutes": 0,
        "on_date": tomorrow.date(),
    }
    WorkDay.create(**kwargs)
    logger.debug(f"added work day for {teacher}")
    resp = requester.post(
        "/appointments/",
        json={
            "date": date,
            "duration": 40,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
        },
    )
    assert "not available" in resp.json["message"]


def test_teacher_new_lesson_without_student(auth, teacher, student, requester):
    auth.login(email=teacher.user.email)
    date = (tomorrow.replace(hour=13, minute=00)).strftime(DATE_FORMAT)
    resp = requester.post("/appointments/", json={"date": date, "duration": 40})
    assert "does not exist" in resp.json["message"]


def test_teacher_new_lesson_with_student(auth, teacher, student, requester):
    auth.login(email=teacher.user.email)
    date = (tomorrow.replace(hour=13, minute=00)).strftime(DATE_FORMAT)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date,
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    assert resp.json["data"]["is_approved"]
    assert resp.json["data"]["price"] == student.price


def test_teacher_new_lesson_with_existing_lessons(
    auth, teacher, meetup, dropoff, student, requester
):
    auth.login(email=teacher.user.email)
    date = tomorrow.replace(hour=13, minute=00)
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.replace(minute=30).strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    assert "not available" in resp.json["message"]
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.replace(hour=12, minute=30).strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    assert "not available" in resp.json["message"]


def test_teacher_new_test_with_existing_lessons(
    auth, teacher, student, requester, meetup, dropoff
):
    auth.login(email=teacher.user.email)
    date = tomorrow.replace(hour=13, minute=00)
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    assert not lesson.deleted
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.replace(minute=30).strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
            "type": "test",
        },
    )
    assert lesson.deleted


def test_teacher_new_consecutive_lessons(auth, teacher, student, requester):
    auth.login(email=teacher.user.email)
    date = tomorrow.replace(hour=13, minute=00)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    date = date.replace(minute=40)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    assert resp.json["data"]
    date = date.replace(hour=12, minute=20, second=59)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
        },
    )
    assert resp.json["data"]


def test_teacher_past_lesson(auth, teacher, student, requester, meetup, dropoff):
    auth.login(email=teacher.user.email)
    date = datetime.now() - timedelta(days=3)
    resp = requester.post(
        "/appointments/",
        json={
            "date": date.strftime(DATE_FORMAT),
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "duration": 40,
            "type": "test",
        },
    )
    assert resp.json["data"]


def test_delete_lesson(auth, teacher, student, meetup, dropoff, requester):
    lesson = create_lesson(
        teacher, student, meetup, dropoff, datetime.utcnow() + timedelta(hours=23)
    )
    auth.login(email=student.user.email)
    resp = requester.delete(f"/appointments/{lesson.id}")
    assert (
        "This appointment is either in the past or in less than 24 hours."
        == resp.json["message"]
    )
    lesson.update(date=datetime.utcnow() - timedelta(hours=2))
    resp = requester.delete(f"/appointments/{lesson.id}")
    assert (
        "This appointment is either in the past or in less than 24 hours."
        == resp.json["message"]
    )
    lesson.update(date=datetime.utcnow() + timedelta(days=2))
    resp = requester.delete(f"/appointments/{lesson.id}")
    assert "successfully" in resp.json["message"]


def test_approve_lesson(auth, teacher, student, meetup, dropoff, requester):
    lesson = create_lesson(teacher, student, meetup, dropoff, datetime.utcnow())
    auth.login(email=teacher.user.email)
    resp = requester.get(f"/appointments/{lesson.id}/approve")
    assert "approved" in resp.json["message"]
    resp = requester.get(f"/appointments/7/approve")
    assert "not exist" in resp.json["message"]
    assert lesson.is_approved

    # now we create 2 lessons at the same date - 1 of them approved.
    # we shouldn't be able to approve the 2nd one
    date = datetime.utcnow()
    create_lesson(teacher, student, meetup, dropoff, date)
    second = create_lesson(teacher, student, meetup, dropoff, date, is_approved=False)
    resp = requester.get(f"/appointments/{second.id}/approve")
    assert "There is another lesson at the same time" in resp.json["message"]


def test_user_edit_lesson(app, auth, student, teacher, meetup, dropoff, requester):
    """ test that is_approved turns false when user edits lesson"""
    date = datetime.utcnow() + timedelta(minutes=5)
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    assert lesson.meetup_place.google_id == "ID1"
    times_used = lesson.meetup_place.times_used
    auth.login(email=student.user.email)
    resp = requester.post(
        f"/appointments/{lesson.id}",
        json={
            "duration": 40,
            "date": date.strftime(DATE_FORMAT),
            "meetup_place": {"description": lesson.meetup_place.description},
        },
    )
    lesson = Appointment.query.filter_by(id=lesson.id).first()
    assert lesson.meetup_place.google_id == "ID1"
    assert lesson.meetup_place.times_used == times_used
    assert "successfully" in resp.json["message"]
    assert "test" == resp.json["data"]["meetup_place"]
    assert not resp.json["data"]["is_approved"]
    resp = requester.post(
        f"/appointments/{lesson.id}",
        json={
            "duration": 40,
            "date": date.strftime(DATE_FORMAT),
            "meetup_place": {"description": "no"},
            "dropoff_place": {"description": None},
        },
    )
    assert "no" == resp.json["data"]["meetup_place"]
    auth.logout()
    auth.login(email=teacher.user.email)
    resp = requester.post(
        f"/appointments/{lesson.id}",
        json={
            "duration": 40,
            "date": date.strftime(DATE_FORMAT),
            "meetup_place": {"description": "yes"},
            "student_id": student.id,
        },
    )
    assert "yes" == resp.json["data"]["meetup_place"]
    assert resp.json["data"]["is_approved"]


def test_teacher_edit_current_lesson(
    auth, student, teacher, meetup, dropoff, requester
):
    date = datetime.utcnow()
    lesson = create_lesson(teacher, student, meetup, dropoff, date)
    auth.login(email=teacher.user.email)
    resp = requester.post(
        f"/appointments/{lesson.id}",
        json={
            "duration": 80,
            "date": date.strftime(DATE_FORMAT),
            "meetup_place": {"description": "yes"},
            "student_id": student.id,
        },
    )
    assert "yes" == resp.json["data"]["meetup_place"]
    assert resp.json["data"]["is_approved"]


def test_handle_places(student: Student, meetup: Place, teacher, dropoff):
    assert handle_places(
        {
            "meetup_place": dict(description="test", google_id="ID1"),
            "dropoff_place": dict(description="test2", google_id="ID2"),
        },
        None,
    ) == (None, None)
    assert handle_places(
        {"meetup_place": dict(description=meetup.description), "dropoff_place": None},
        student,
    ) == (meetup, None)
    new_meetup, new_dropoff = handle_places(
        {
            "meetup_place": dict(description="aa", google_id="ID1"),
            "dropoff_place": dict(description="bb"),
        },
        student,
    )
    assert new_meetup.description == "aa"
    assert new_meetup.times_used == 1
    assert new_meetup.google_id == "ID1"
    assert new_dropoff.times_used == 1

    appointment = create_lesson(teacher, student, meetup, dropoff, datetime.utcnow())
    assert handle_places(
        {
            "meetup_place": dict(description=meetup.description),
            "dropoff_place": dict(description=dropoff.description),
        },
        student,
        appointment,
    ) == (None, None)


@pytest.mark.parametrize(
    ("data_dict", "error"),
    (
        (
            {
                "duration": 40,
                "date": (datetime.utcnow() - timedelta(minutes=2)).strftime(
                    DATE_FORMAT
                ),
            },
            "Date is not valid.",
        ),
        (
            {"duration": 40, "date": (tomorrow.strftime(DATE_FORMAT))},
            "This hour is not available.",
        ),
        ({"date": (tomorrow.strftime(DATE_FORMAT))}, "Duration is required."),
    ),
)
def test_student_invalid_get_data(student, data_dict: dict, error: str):
    with pytest.raises(RouteError) as e:
        get_data(data_dict, student.user)
    assert e.value.description == error


@pytest.mark.parametrize(
    ("data_dict", "error"),
    (
        (
            {
                "duration": 40,
                "date": (datetime.utcnow() + timedelta(days=2))
                .replace(hour=10, minute=0)
                .strftime(DATE_FORMAT),
                "student_id": 0,
            },
            "Student does not exist.",
        ),
    ),
)
def test_teacher_invalid_get_data(teacher, data_dict: dict, error: str):
    with pytest.raises(RouteError) as e:
        get_data(data_dict, teacher.user)
    assert e.value.description == error


def test_valid_get_data(student):
    date = ((tomorrow + timedelta(days=1)).replace(hour=00, minute=00)).strftime(
        DATE_FORMAT
    )
    data_dict = {
        "duration": 40,
        "date": date,
        "meetup_place": {"description": "test"},
        "dropoff_place": {"description": "test"},
    }
    get_data(data_dict, student.user)


def test_lesson_number(teacher, student, meetup, dropoff):
    lessons = []
    for i in range(2):
        lessons.append(
            create_lesson(
                teacher,
                student,
                meetup,
                dropoff,
                datetime.utcnow() + timedelta(minutes=i),
            )
        )

    assert lessons[1].lesson_number == 2

    # now lesson number should be 1, because it's the earliest
    new_lesson = create_lesson(
        teacher, student, meetup, dropoff, datetime.utcnow() - timedelta(hours=10)
    )
    assert new_lesson.lesson_number == 1
    assert lessons[1].lesson_number == 3

    lesson = create_lesson(
        teacher,
        student,
        meetup,
        dropoff,
        datetime.utcnow() + timedelta(minutes=5),
        duration=60,
    )
    assert lesson.lesson_number == 4.5


def test_topics_for_lesson(app):
    topic = Topic.create(
        title="not important", min_lesson_number=1, max_lesson_number=2
    )
    assert topic in Topic.for_lesson(1)


def test_payments(auth, teacher, student, requester):
    payments = []
    for x in range(4):
        payments.append(
            Payment.create(teacher=teacher, student=student, amount=x * 100)
        )

    auth.login(email=teacher.user.email)
    resp = requester.get("/appointments/payments?limit=2")
    assert len(resp.json["data"]) == 2
    assert resp.json["data"][0]["id"] == payments[-1].id

    Payment.create(
        teacher=teacher,
        student=student,
        amount=100_000,
        created_at=datetime.utcnow().replace(month=datetime.utcnow().month + 1),
    )
    start_of_month = datetime.today().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    end_of_month = datetime.today().replace(
        day=28, hour=0, minute=0, second=0, microsecond=0
    )
    start_next_month = start_of_month + relativedelta.relativedelta(months=1)
    end_next_month = end_of_month + relativedelta.relativedelta(months=1)
    start_next_month = start_next_month.strftime(DATE_FORMAT)
    start_of_month = start_of_month.strftime(DATE_FORMAT)
    end_next_month = end_next_month.strftime(DATE_FORMAT)
    resp = requester.get(
        f"/appointments/payments?created_at=ge:{start_next_month}&created_at=lt:{end_next_month}"
    )
    assert resp.json["data"][0]["amount"] == 100_000
    resp = requester.get(
        f"/appointments/payments?created_at=ge:{start_of_month}&created_at=lt:{start_of_month}"
    )
    assert not resp.json["data"]


def test_lesson_topics(auth, requester, student, meetup, dropoff, topic, teacher):
    """test for:
    1. lesson without topics
    2. lesson with finished topics
    3. lesson without topics, but user with topics"""
    lesson = create_lesson(teacher, student, meetup, dropoff, datetime.utcnow())
    auth.login(email=teacher.user.email)
    resp = requester.get(f"/appointments/{lesson.id}/topics")
    assert resp.json["available"][0]["id"] == topic.id
    another_topic = Topic.create(
        title="test3", min_lesson_number=20, max_lesson_number=22
    )
    requester.post(
        f"/appointments/{lesson.id}/topics",
        json={"topics": {"progress": [topic.id], "finished": []}},
    )
    requester.post(
        f"/appointments/{lesson.id}/topics",
        json={"topics": {"progress": [another_topic.id], "finished": [topic.id]}},
    )
    resp = requester.get(f"/appointments/{lesson.id}/topics")
    lesson_topics = [topic["id"] for topic in resp.json["available"]]
    assert another_topic.id in resp.json["progress"]
    assert another_topic.id in lesson_topics
    assert topic.id in resp.json["finished"]
    assert topic.id in lesson_topics

    another_lesson = create_lesson(teacher, student, meetup, dropoff, datetime.utcnow())
    resp = requester.get(f"/appointments/{another_lesson.id}/topics")
    assert another_topic.id == resp.json["available"][0]["id"]
    assert topic.id not in [topic["id"] for topic in resp.json["available"]]
    assert len(resp.json["available"]) == 1

    # if we have 2 lessons with same topic, topic is finished on the 2nd
    requester.post(
        f"/appointments/{lesson.id}/topics",
        json={"topics": {"progress": [], "finished": [another_topic.id]}},
    )
    resp = requester.get(f"/appointments/{lesson.id}/topics")
    assert another_topic.id in [topic["id"] for topic in resp.json["available"]]
    assert another_topic.id in resp.json["finished"]


def test_new_lesson_topics(
    auth, requester, student, meetup, dropoff, topic, lesson, teacher
):
    auth.login(email=teacher.user.email)
    resp = requester.get(f"/appointments/0/topics")
    assert "Lesson does not exist" in resp.json["message"]
    resp = requester.get(f"/appointments/0/topics?student_id=1000")
    assert "Lesson does not exist" in resp.json["message"]
    another_topic = Topic.create(
        title="test3", min_lesson_number=20, max_lesson_number=22
    )
    requester.post(
        f"/appointments/{lesson.id}/topics",
        json={"topics": {"progress": [another_topic.id], "finished": [topic.id]}},
    )
    requester.get(f"/appointments/{lesson.id}/topics")
    resp = requester.get(f"/appointments/0/topics?student_id={student.id}")
    assert resp.json["available"][0]["id"] == another_topic.id


def test_teacher_adding_test(auth, teacher, student, requester):
    auth.login(email=teacher.user.email)
    date = (tomorrow.replace(hour=13, minute=00)).strftime(DATE_FORMAT)
    resp = requester.post(
        "/appointments/",
        json={
            "duration": 40,
            "date": date,
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "type": "test",
        },
    )
    assert resp.json["data"]["type"] == AppointmentType.TEST.name.lower()


def test_student_adding_inner_exam(auth, teacher, student, requester):
    auth.login(email=student.user.email)
    kwargs = {
        "teacher": teacher,
        "day": 1,
        "from_hour": 7,
        "from_minutes": 0,
        "to_hour": 21,
        "to_minutes": 59,
        "on_date": tomorrow.date(),
    }
    WorkDay.create(**kwargs)
    date = (tomorrow.replace(hour=21, minute=00)).strftime(DATE_FORMAT)
    resp = requester.post(
        "/appointments/",
        json={
            "duration": 40,
            "date": date,
            "student_id": student.id,
            "meetup_place": {"description": "test"},
            "dropoff_place": {"description": "test"},
            "type": "inner_exam",
        },
    )
    assert resp.json["data"]["type"] == AppointmentType.LESSON.name.lower()


@pytest.mark.parametrize(
    ("date", "end_date", "result"),
    (
        (tomorrow, tomorrow + timedelta(minutes=60), True),
        (tomorrow.replace(minute=10), tomorrow + timedelta(minutes=40), True),
        (tomorrow - timedelta(hours=1), tomorrow + timedelta(minutes=30), True),
        (tomorrow + timedelta(minutes=10), tomorrow + timedelta(minutes=50), True),
        (tomorrow + timedelta(minutes=40), tomorrow + timedelta(minutes=50), False),
        (tomorrow - timedelta(hours=1), tomorrow, False),
        (tomorrow, tomorrow + timedelta(minutes=40), True),
    ),
)
def test_appointments_between(
    teacher, student, requester, meetup, dropoff, date, end_date, result
):
    """1. get lessons with the same starting hour
    2. get lessons with the same ending hour
    3. get lessons that end within existing hours
    4. get lessons that start within existing hours
    5. lessons that start when existing lesson ends
    6. lesson that ends when existing lesson starts
    7. exactly the same hours
    """
    lesson = create_lesson(teacher, student, meetup, dropoff, tomorrow)
    existing_lessons = Appointment.query.filter(Appointment.appointments_between(date, end_date)).all()
    assert (lesson in existing_lessons) == result
