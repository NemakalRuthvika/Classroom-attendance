#Classroom-attendance

Student Attendance System for classroom attendance records.

## Stack

- HTML, CSS
- Python Flask
- MongoDB Atlas
- Login and CRUD operations

## Features

- Teacher/admin login
- Student create, read, update, delete
- Daily attendance marking with Present, Absent, and Late status
- One attendance record per student per date
- Dashboard summary for today
- Searchable student list
- Filterable attendance reports

## Default Login

```text
Email: admin@example.com
Password: Admin@123
```

You can override these values with `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_NAME`.

## MongoDB

The app defaults to:

```text
MONGODB_DB_NAME=exam_system
```

The MongoDB URI is read from `MONGODB_URI`. For Render, add your Atlas URI as a protected environment variable.

Collections used by this project:

- `classroom_attendance_users`
- `classroom_attendance_students`
- `classroom_attendance_records`

## Run

```powershell
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Render Deploy

This repository includes `render.yaml`. In Render, set:

```text
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>/<database>?retryWrites=true&w=majority
ADMIN_PASSWORD=<your-secure-password>
```

`MONGODB_DB_NAME` is already configured as `exam_system`.

## GitHub Actions

The workflow at `.github/workflows/ci.yml` installs dependencies, compiles `app.py`, and verifies the Flask app imports on every push or pull request to `main`.
"# Classroom-attendance" 
