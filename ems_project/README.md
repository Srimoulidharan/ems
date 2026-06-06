# Enterprise Employee Management System (Django)

A production-style corporate EMS built with Django templates, SQLite for local/demo use, role-based access control, secure password hashing, employee records, attendance, leave workflow, payroll, performance, documents, reports, notifications, holidays and audit logs.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Admin | admin@company.com | admin123 |
| HR | hr@company.com | hr123 |
| Manager | manager@company.com | manager123 |
| Employee | employee@company.com | employee123 |
| Manager 2 | manager2@company.com | manager2123 |
| Employee 2 | employee2@company.com | employee2123 |

## Run locally

```bash
cd ems_enterprise
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

Open `http://127.0.0.1:8000/`.

## Corporate features

- Email + password login with automatic role identification.
- Passwords stored using Django password hashing.
- Admin, HR, Manager and Employee roles.
- Admin/HR can access all employee data.
- Managers can access only employees assigned to them.
- Employees can access only their own records.
- Leave workflow with role restrictions and approver tracking.
- Leave balances by leave type and year.
- Attendance check-in/check-out and team reports.
- Employee onboarding and department management.
- Task assignment, submission, manager review and feedback.
- Payroll records with net pay calculation.
- Performance scorecards.
- Employee document upload with role visibility.
- Holiday calendar.
- Notifications.
- CSV reports/export for employees, attendance, leave and payroll.
- Audit logs.
- Django admin at `/admin-panel/`.

## Production deployment notes

For an actual company deployment, set environment variables and use PostgreSQL/MySQL instead of SQLite:

```bash
DJANGO_SECRET_KEY=change-this-to-a-long-random-secret
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DJANGO_SECURE_SSL=1
```

Recommended real deployment additions:

- PostgreSQL/MySQL database.
- HTTPS and secure cookies enabled.
- Email backend for password reset and notifications.
- Object storage for documents.
- Regular database backups.
- Dedicated audit and monitoring tools.
- Company-specific payroll/tax rules.

