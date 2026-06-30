import os
from datetime import date, datetime
from functools import wraps

from dotenv import load_dotenv
from bson import ObjectId
from bson.errors import InvalidId
from flask import Flask, flash, redirect, render_template, request, session, url_for
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

# Load variables from .env file
load_dotenv()

# Default local MongoDB URI (fallback)
DEFAULT_MONGODB_URI = "mongodb://localhost:27017/"

app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get(
        "SECRET_KEY",
        "classroom-attendance-dev-key"
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# Read MongoDB URI from .env file
MONGODB_URI = (
    os.environ.get("MONGODB_URI")
    or os.environ.get("MONGO_URI")
    or DEFAULT_MONGODB_URI
)


# Database name
MONGODB_DB_NAME = (
    os.environ.get("MONGODB_DB_NAME")
    or os.environ.get("MONGO_DATABASE")
    or "exam_system"
)

mongo_client = None


def get_mongo_client():
    global mongo_client

    if mongo_client is None:
        mongo_client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000
        )

    return mongo_client

class LazyCollection:
    def __init__(self, name):
        self.name = name

    def collection(self):
        return get_mongo_client()[MONGODB_DB_NAME][self.name]

    def __getattr__(self, item):
        return getattr(self.collection(), item)


users_collection = LazyCollection("classroom_attendance_users")
students_collection = LazyCollection("classroom_attendance_students")
attendance_collection = LazyCollection("classroom_attendance_records")

SETUP_DONE = False


def setup_database():
    global SETUP_DONE
    if SETUP_DONE:
        return

    users_collection.create_index([("email", ASCENDING)], unique=True)
    students_collection.create_index([("roll_no", ASCENDING)], unique=True)
    attendance_collection.create_index(
        [("attendance_date", DESCENDING), ("student_id", ASCENDING)]
    )

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    if users_collection.find_one({"email": admin_email}) is None:
        users_collection.insert_one(
            {
                "name": os.environ.get("ADMIN_NAME", "Class Teacher"),
                "email": admin_email,
                "password_hash": generate_password_hash(admin_password),
                "role": "admin",
                "created_at": datetime.utcnow(),
            }
        )
    SETUP_DONE = True


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to manage classroom attendance.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def serialize_document(document):
    if document is None:
        return None
    document["id"] = str(document["_id"])
    return document


def object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def database_ready():
    try:
        setup_database()
        return True
    except PyMongoError as exc:
        flash(f"MongoDB connection error: {exc}", "error")
        return False


def student_form_data():
    return {
        "roll_no": request.form.get("roll_no", "").strip().upper(),
        "name": request.form.get("name", "").strip(),
        "class_name": request.form.get("class_name", "").strip(),
        "section": request.form.get("section", "").strip().upper(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "status": request.form.get("status", "Active"),
        "updated_at": datetime.utcnow(),
    }


def validate_student(student):
    required = ["roll_no", "name", "class_name", "section"]
    if any(not student[field] for field in required):
        return "Roll number, name, class, and section are required."
    if student["email"] and "@" not in student["email"]:
        return "Enter a valid student email address."
    if student["status"] not in {"Active", "Inactive"}:
        return "Select a valid student status."
    return None


def current_user():
    if "user_id" not in session:
        return None
    user_oid = object_id(session["user_id"])
    if user_oid is None:
        return None
    return serialize_document(users_collection.find_one({"_id": user_oid}, {"password_hash": 0}))


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    email = request.form.get("email", "").strip().lower()
    if request.method == "POST":
        if not database_ready():
            return render_template("login.html", email=email)
        password = request.form.get("password", "")
        user = serialize_document(users_collection.find_one({"email": email}))
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash(f"Welcome back, {user['name']}.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")

    return render_template("login.html", email=email)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    if not database_ready():
        return render_template("dashboard.html", stats={}, recent_records=[])

    today = date.today().isoformat()
    total_students = students_collection.count_documents({"status": "Active"})
    today_records = list(attendance_collection.find({"attendance_date": today}))
    present_today = sum(1 for record in today_records if record["status"] == "Present")
    absent_today = sum(1 for record in today_records if record["status"] == "Absent")
    late_today = sum(1 for record in today_records if record["status"] == "Late")
    attendance_rate = round((present_today / total_students) * 100, 1) if total_students else 0
    recent_records = [
        serialize_document(record)
        for record in attendance_collection.find().sort("_id", DESCENDING).limit(8)
    ]

    stats = {
        "total_students": total_students,
        "present_today": present_today,
        "absent_today": absent_today,
        "late_today": late_today,
        "attendance_rate": attendance_rate,
        "today": today,
    }
    return render_template("dashboard.html", stats=stats, recent_records=recent_records)


@app.route("/students", methods=["GET", "POST"])
@login_required
def students():
    if not database_ready():
        return render_template("students.html", students=[], editing=None)

    if request.method == "POST":
        student = student_form_data()
        error = validate_student(student)
        if error:
            flash(error, "error")
        else:
            student["created_at"] = datetime.utcnow()
            try:
                students_collection.insert_one(student)
                flash(f"{student['name']} was added.", "success")
                return redirect(url_for("students"))
            except PyMongoError as exc:
                flash(f"Could not save student: {exc}", "error")

    query = request.args.get("q", "").strip()
    filter_query = {}
    if query:
        filter_query = {
            "$or": [
                {"roll_no": {"$regex": query, "$options": "i"}},
                {"name": {"$regex": query, "$options": "i"}},
                {"class_name": {"$regex": query, "$options": "i"}},
                {"section": {"$regex": query, "$options": "i"}},
            ]
        }
    all_students = [
        serialize_document(student)
        for student in students_collection.find(filter_query).sort("roll_no", ASCENDING)
    ]
    return render_template("students.html", students=all_students, editing=None, query=query)


@app.route("/students/<student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    if not database_ready():
        return redirect(url_for("students"))

    student_oid = object_id(student_id)
    if student_oid is None:
        flash("Student not found.", "error")
        return redirect(url_for("students"))

    existing = serialize_document(students_collection.find_one({"_id": student_oid}))
    if existing is None:
        flash("Student not found.", "error")
        return redirect(url_for("students"))

    if request.method == "POST":
        student = student_form_data()
        error = validate_student(student)
        if error:
            flash(error, "error")
        else:
            try:
                students_collection.update_one({"_id": student_oid}, {"$set": student})
                flash(f"{student['name']} was updated.", "success")
                return redirect(url_for("students"))
            except PyMongoError as exc:
                flash(f"Could not update student: {exc}", "error")

    all_students = [
        serialize_document(student)
        for student in students_collection.find().sort("roll_no", ASCENDING)
    ]
    return render_template("students.html", students=all_students, editing=existing, query="")


@app.route("/students/<student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    if database_ready():
        student_oid = object_id(student_id)
        if student_oid is not None:
            students_collection.delete_one({"_id": student_oid})
            attendance_collection.delete_many({"student_id": student_id})
            flash("Student and related attendance records were deleted.", "success")
    return redirect(url_for("students"))


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    if not database_ready():
        return render_template("attendance.html", students=[], records=[], today=date.today().isoformat())

    all_students = [
        serialize_document(student)
        for student in students_collection.find({"status": "Active"}).sort("roll_no", ASCENDING)
    ]
    selected_date = request.values.get("attendance_date") or date.today().isoformat()

    if request.method == "POST":
        student_id = request.form.get("student_id", "")
        student_oid = object_id(student_id)
        student = serialize_document(students_collection.find_one({"_id": student_oid})) if student_oid else None
        status = request.form.get("status", "Present")
        if student is None:
            flash("Select a valid student.", "error")
        elif status not in {"Present", "Absent", "Late"}:
            flash("Select a valid attendance status.", "error")
        else:
            document = {
                "student_id": student["id"],
                "roll_no": student["roll_no"],
                "student_name": student["name"],
                "class_name": student["class_name"],
                "section": student["section"],
                "attendance_date": selected_date,
                "status": status,
                "remarks": request.form.get("remarks", "").strip(),
                "marked_by": session.get("user_name", "Admin"),
                "updated_at": datetime.utcnow(),
            }
            attendance_collection.update_one(
                {"student_id": student["id"], "attendance_date": selected_date},
                {"$set": document, "$setOnInsert": {"created_at": datetime.utcnow()}},
                upsert=True,
            )
            flash(f"Attendance marked for {student['name']}.", "success")
            return redirect(url_for("attendance", attendance_date=selected_date))

    records = [
        serialize_document(record)
        for record in attendance_collection.find({"attendance_date": selected_date}).sort("roll_no", ASCENDING)
    ]
    return render_template(
        "attendance.html",
        students=all_students,
        records=records,
        today=selected_date,
    )


@app.route("/attendance/<record_id>/delete", methods=["POST"])
@login_required
def delete_attendance(record_id):
    if database_ready():
        record_oid = object_id(record_id)
        if record_oid is not None:
            attendance_collection.delete_one({"_id": record_oid})
            flash("Attendance record deleted.", "success")
    return redirect(url_for("attendance", attendance_date=request.form.get("attendance_date")))


@app.route("/reports")
@login_required
def reports():
    if not database_ready():
        return render_template("reports.html", records=[], summary={}, filters={})

    filters = {
        "attendance_date": request.args.get("attendance_date", "").strip(),
        "class_name": request.args.get("class_name", "").strip(),
        "section": request.args.get("section", "").strip().upper(),
        "status": request.args.get("status", "").strip(),
    }
    mongo_filter = {key: value for key, value in filters.items() if value}
    records = [
        serialize_document(record)
        for record in attendance_collection.find(mongo_filter).sort(
            [("attendance_date", DESCENDING), ("roll_no", ASCENDING)]
        )
    ]
    summary = {
        "total": len(records),
        "present": sum(1 for record in records if record["status"] == "Present"),
        "absent": sum(1 for record in records if record["status"] == "Absent"),
        "late": sum(1 for record in records if record["status"] == "Late"),
    }
    return render_template("reports.html", records=records, summary=summary, filters=filters)


@app.get("/health")
def health():
    return {"status": "ok", "database": MONGODB_DB_NAME}


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
        port=int(os.environ.get("PORT", "5000")),
    )
