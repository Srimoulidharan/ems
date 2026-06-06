from datetime import datetime
import csv
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    Announcement, Attendance, AuditLog, Department, EmployeeDocument, Holiday, LeaveBalance,
    LeaveRequest, Notification, Payroll, PerformanceReview, Shift, Task, UserProfile
)

VALID_ROLES = {'employee', 'manager', 'admin', 'hr'}


def log(actor, action, details=''):
    try:
        AuditLog.objects.create(actor=actor or 'system', action=action, details=details)
    except Exception:
        pass


def ensure_leave_balances(user):
    year = timezone.localdate().year
    for leave_type, opening in [('Casual Leave', 12), ('Sick Leave', 8), ('Earned Leave', 12)]:
        LeaveBalance.objects.get_or_create(
            employee=user,
            year=year,
            leave_type=leave_type,
            defaults={'opening_balance': opening, 'credited': 0, 'used': 0, 'adjusted': 0},
        )


def create_notification(recipient, title, message):
    try:
        Notification.objects.create(recipient=recipient, title=title, message=message)
    except Exception:
        pass


def password_matches(raw, stored):
    if not stored:
        return False
    if stored.startswith(('pbkdf2_', 'argon2$', 'bcrypt')):
        return check_password(raw, stored)
    return raw == stored


def seed_defaults():
    departments = [
        ('Administration', 'ADM', 'Admin User'), ('Human Resources', 'HR', 'HR User'),
        ('Engineering', 'ENG', 'Engineering Manager'), ('Operations', 'OPS', 'Operations Manager'),
        ('Finance', 'FIN', 'Admin User')
    ]
    dep_map = {}
    for name, code, head in departments:
        dep, _ = Department.objects.update_or_create(code=code, defaults={'name': name, 'head': head, 'location': 'Head Office'})
        dep_map[code] = dep

    demo_users = [
        dict(userId='EMP-0001', username='admin', password='admin123', role='admin', full_name='Admin User', designation='System Administrator', department=dep_map['ADM'], email='admin@company.com', phone='9000000001', salary_ctc=1200000),
        dict(userId='EMP-0002', username='hr', password='hr123', role='hr', full_name='HR User', designation='HR Executive', department=dep_map['HR'], email='hr@company.com', phone='9000000002', salary_ctc=800000),
        dict(userId='EMP-0003', username='manager', password='manager123', role='manager', full_name='Engineering Manager', designation='Engineering Manager', department=dep_map['ENG'], email='manager@company.com', phone='9000000003', salary_ctc=1500000),
        dict(userId='EMP-0004', username='employee', password='employee123', role='employee', full_name='Employee User', designation='Software Engineer', department=dep_map['ENG'], email='employee@company.com', phone='9000000004', salary_ctc=700000, projectWorkingOn='Corporate EMS Upgrade'),
        dict(userId='EMP-0005', username='manager2', password='manager2123', role='manager', full_name='Operations Manager', designation='Operations Manager', department=dep_map['OPS'], email='manager2@company.com', phone='9000000005', salary_ctc=1400000),
        dict(userId='EMP-0006', username='employee2', password='employee2123', role='employee', full_name='Operations Employee', designation='Operations Executive', department=dep_map['OPS'], email='employee2@company.com', phone='9000000006', salary_ctc=600000, projectWorkingOn='Operations Automation'),
    ]
    for item in demo_users:
        raw_password = item.pop('password')
        user, created = UserProfile.objects.update_or_create(
            username=item['username'],
            defaults={**item, 'leaveBalance': 32, 'employment_status': 'Active'}
        )
        # Store demo passwords securely. Existing plain-text passwords are upgraded on startup.
        if created or not user.password or not user.password.startswith('pbkdf2_'):
            user.password = make_password(raw_password)
            user.save(update_fields=['password'])
        ensure_leave_balances(user)

    manager = UserProfile.objects.filter(username='manager').first()
    employee = UserProfile.objects.filter(username='employee').first()
    if employee and manager:
        employee.manager = manager
        employee.save(update_fields=['manager'])

    manager2 = UserProfile.objects.filter(username='manager2').first()
    employee2 = UserProfile.objects.filter(username='employee2').first()
    if employee2 and manager2:
        employee2.manager = manager2
        employee2.save(update_fields=['manager'])

    Shift.objects.get_or_create(name='General Shift', defaults={'start_time': '09:30', 'end_time': '18:30', 'grace_minutes': 15})
    for title, date in [('New Year', f'{timezone.localdate().year}-01-01'), ('Independence Day', f'{timezone.localdate().year}-08-15'), ('Republic Day', f'{timezone.localdate().year}-01-26')]:
        Holiday.objects.get_or_create(date=date, defaults={'name': title, 'location': 'India'})

    if Announcement.objects.count() == 0:
        admin = UserProfile.objects.filter(username='admin').first()
        Announcement.objects.create(title='Welcome to Enterprise EMS', message='Use this secure corporate EMS for employee records, attendance, leave approvals, payroll, task tracking, documents, reports and performance reviews.', audience='All', created_by=admin)


def current_user(request):
    uid = request.session.get('profile_id')
    return UserProfile.objects.filter(id=uid).first() if uid else None


def login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        seed_defaults()
        user = current_user(request)
        if not user:
            messages.warning(request, 'Please login first.')
            return redirect('login')
        request.profile = user
        return view(request, *args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.profile.role not in roles:
                messages.error(request, 'You do not have permission to access this page.')
                return redirect('dashboard')
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def parse_skillset(value):
    return [x.strip() for x in (value or '').split(',') if x.strip()]


def base_context(request, **kwargs):
    data = {'me': getattr(request, 'profile', current_user(request))}
    data.update(kwargs)
    return data


def managed_employee_queryset(user, include_self=False):
    """Return the employee records a logged-in user is allowed to see/manage.

    Admin and HR can access everyone. Managers can access only employees who are
    explicitly assigned to them through the manager field. Employees can access
    only their own record. This function is used in both page display and POST
    actions so permissions cannot be bypassed by changing form IDs.
    """
    qs = UserProfile.objects.select_related('department', 'manager').order_by('userId')
    if user.role in ['admin', 'hr']:
        return qs
    if user.role == 'manager':
        qs = qs.filter(manager=user)
        if include_self:
            qs = qs | UserProfile.objects.filter(id=user.id)
        return qs.distinct()
    return qs.filter(id=user.id)


def can_manage_employee(actor, employee):
    if actor.role in ['admin', 'hr']:
        return True
    if actor.role == 'manager':
        return employee.manager_id == actor.id
    return employee.id == actor.id


def can_approve_leave(actor, leave):
    """Leave approval rule: Admin/HR can approve all.
    Managers can approve only leaves of employees assigned to them. Nobody can
    approve their own leave request.
    """
    if actor.id == leave.user_id:
        return False
    if actor.role in ['admin', 'hr']:
        return True
    if actor.role == 'manager':
        return leave.user.manager_id == actor.id
    return False


def home(request):
    return login_view(request)


def login_view(request):
    seed_defaults()
    if current_user(request):
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '').strip()

        user = UserProfile.objects.filter(
            email__iexact=email,
            employment_status='Active'
        ).first()

        if user and password_matches(password, user.password):
            if not user.password.startswith('pbkdf2_'):
                user.password = make_password(password)
            user.failed_login_attempts = 0
            user.last_login_at = timezone.now()
            user.save(update_fields=['password', 'failed_login_attempts', 'last_login_at'])
            request.session['profile_id'] = user.id
            request.session['role'] = user.role
            request.session['username'] = user.username
            request.session['email'] = user.email
            request.session['display_name'] = user.display_name
            log(user.username, 'Logged in', f'Email login: {user.email}, role: {user.role}')
            return redirect('dashboard')

        if user:
            user.failed_login_attempts += 1
            user.save(update_fields=['failed_login_attempts'])
        messages.error(request, 'Invalid email or password, or your account is inactive. Try admin@company.com / admin123.')

    return render(request, 'ems/login.html')


def logout_view(request):
    username = request.session.get('username')
    request.session.flush()
    log(username, 'Logged out')
    return redirect('login')


@login_required
def dashboard(request):
    user = request.profile
    visible_users = managed_employee_queryset(user, include_self=True)

    tasks = Task.objects.all()
    leaves = LeaveRequest.objects.all()
    payrolls = Payroll.objects.all()
    if user.role == 'employee':
        tasks = tasks.filter(assignee=user); leaves = leaves.filter(user=user); payrolls = payrolls.filter(employee=user)
    elif user.role == 'manager':
        team_ids = list(user.team_members.values_list('id', flat=True)) + [user.id]
        tasks = tasks.filter(Q(assignee_id__in=team_ids) | Q(assigned_by=user)); leaves = leaves.filter(user_id__in=team_ids); payrolls = payrolls.filter(employee_id__in=team_ids)

    ctx = dict(
        total_users=visible_users.count(), departments=Department.objects.count(),
        active_users=visible_users.filter(employment_status='Active').count(),
        pending_leaves=leaves.filter(status='pending').count(),
        open_tasks=tasks.exclude(status='Approved').count(), completed_tasks=tasks.filter(status='Approved').count(),
        payroll_total=sum([p.net_pay for p in payrolls.filter(status__in=['Processed','Paid'])]),
        announcements=Announcement.objects.order_by('-createdAt')[:5],
        recent_tasks=tasks.select_related('assignee','assigned_by').order_by('-createdAt')[:8],
        recent_leaves=leaves.select_related('user').order_by('-createdAt')[:8],
        dept_breakdown=Department.objects.annotate(emp_count=Count('employees')).order_by('name'),
    )
    return render(request, 'ems/dashboard.html', base_context(request, **ctx))


@role_required('admin', 'hr')
def departments(request):
    if request.method == 'POST':
        Department.objects.update_or_create(
            code=request.POST.get('code','').upper().strip(),
            defaults={'name': request.POST.get('name','').strip(), 'head': request.POST.get('head',''), 'location': request.POST.get('location','')}
        )
        messages.success(request, 'Department saved.')
        return redirect('departments')
    return render(request, 'ems/departments.html', base_context(request, departments=Department.objects.order_by('name')))


@login_required
def employees(request):
    q = request.GET.get('q','').strip(); role = request.GET.get('role',''); dept = request.GET.get('dept','')
    users = managed_employee_queryset(request.profile, include_self=True)
    if role in VALID_ROLES: users = users.filter(role=role)
    if dept: users = users.filter(department_id=dept)
    if q: users = users.filter(Q(username__icontains=q)|Q(full_name__icontains=q)|Q(userId__icontains=q)|Q(email__icontains=q)|Q(designation__icontains=q))
    return render(request, 'ems/employees.html', base_context(request, users=users, q=q, role=role, dept=dept, departments=Department.objects.order_by('name')))


@role_required('admin', 'hr')
def employee_create(request):
    return employee_form(request)


@role_required('admin', 'hr')
def employee_edit(request, pk):
    return employee_form(request, get_object_or_404(UserProfile, pk=pk))


def employee_form(request, item=None):
    if request.method == 'POST':
        data = dict(
            userId=request.POST.get('userId','').strip(), username=request.POST.get('username','').strip(),
            role=request.POST.get('role','employee'), full_name=request.POST.get('full_name','').strip(), email=request.POST.get('email',''), phone=request.POST.get('phone',''),
            designation=request.POST.get('designation',''), department_id=request.POST.get('department') or None, manager_id=request.POST.get('manager') or None,
            employment_status=request.POST.get('employment_status','Active'), work_location=request.POST.get('work_location','Head Office'),
            experience=int(request.POST.get('experience') or 0), skillset=parse_skillset(request.POST.get('skillset')),
            leaveBalance=int(request.POST.get('leaveBalance') or 0), salary_ctc=Decimal(request.POST.get('salary_ctc') or '0'),
            bank_name=request.POST.get('bank_name',''), account_last4=request.POST.get('account_last4','')[-4:], projectWorkingOn=request.POST.get('projectWorkingOn',''), emergency_contact=request.POST.get('emergency_contact','')
        )
        raw_password = request.POST.get('password','').strip()
        if raw_password:
            data['password'] = make_password(raw_password)
        elif not item:
            data['password'] = make_password('Welcome@123')
        try:
            if item:
                for k,v in data.items(): setattr(item,k,v)
                item.save(); messages.success(request, 'Employee updated.'); log(request.profile.username, 'Updated employee', item.username)
            else:
                item = UserProfile.objects.create(**data); ensure_leave_balances(item); messages.success(request, 'Employee onboarded.'); log(request.profile.username, 'Created employee', item.username)
            return redirect('employees')
        except IntegrityError:
            messages.error(request, 'Employee ID or username already exists.')
        except Exception as exc:
            messages.error(request, f'Unable to save employee: {exc}')
    return render(request, 'ems/employee_form.html', base_context(request, item=item, departments=Department.objects.order_by('name'), managers=UserProfile.objects.filter(role='manager').order_by('full_name')))


@role_required('admin', 'hr')
def employee_delete(request, pk):
    item = get_object_or_404(UserProfile, pk=pk)
    if item.username in ['admin','hr','manager','employee']:
        messages.error(request, 'Demo accounts cannot be deleted.')
    elif request.method == 'POST':
        log(request.profile.username, 'Deleted employee', item.username); item.delete(); messages.success(request, 'Employee deleted.')
    return redirect('employees')


@role_required('admin', 'hr', 'manager')
def task_assign(request):
    employees = managed_employee_queryset(request.profile).exclude(role__in=['admin', 'hr']).filter(employment_status='Active').order_by('full_name')
    if request.profile.role == 'manager':
        employees = employees.filter(role='employee')
    if request.method == 'POST':
        assignee = get_object_or_404(employees, pk=request.POST.get('assignee'))
        Task.objects.create(taskName=request.POST.get('taskName',''), taskDescription=request.POST.get('taskDescription',''), priority=request.POST.get('priority','Medium'), deadline=request.POST.get('deadline') or None, assignee=assignee, assigned_by=request.profile, status='Todo')
        messages.success(request, 'Task assigned successfully.'); log(request.profile.username, 'Assigned task', assignee.username); return redirect('tasks')
    return render(request, 'ems/task_form.html', base_context(request, employees=employees))


@login_required
def tasks_list(request):
    user = request.profile; status = request.GET.get('status','')
    tasks = Task.objects.select_related('assignee','assigned_by').order_by('-createdAt')
    if user.role == 'employee': tasks = tasks.filter(assignee=user)
    elif user.role == 'manager': tasks = tasks.filter(Q(assignee__manager=user) | Q(assignee=user))
    if status: tasks = tasks.filter(status=status)
    return render(request, 'ems/tasks.html', base_context(request, tasks=tasks, status=status))


@login_required
def task_submit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if task.assignee_id != request.profile.id:
        messages.error(request, 'You can only submit tasks assigned to you.'); return redirect('tasks')
    if request.method == 'POST':
        task.submittedWork = request.POST.get('submittedWork',''); task.progress = int(request.POST.get('progress') or 100); task.status = 'In Review'; task.submissionDate = timezone.now(); task.save()
        messages.success(request, 'Task submitted for review.'); return redirect('tasks')
    return render(request, 'ems/task_submit.html', base_context(request, task=task))


@role_required('admin', 'hr', 'manager')
def task_review(request, pk):
    task = get_object_or_404(Task.objects.select_related('assignee'), pk=pk)
    if request.profile.role == 'manager' and task.assignee.manager_id != request.profile.id:
        messages.error(request, 'Managers can review only tasks of employees assigned to them.')
        return redirect('tasks')
    if request.method == 'POST':
        task.status = request.POST.get('status', task.status); task.manager_feedback = request.POST.get('manager_feedback',''); task.progress = int(request.POST.get('progress') or task.progress); task.save()
        messages.success(request, 'Task reviewed.'); log(request.profile.username, 'Reviewed task', task.taskName)
    return redirect('tasks')


@login_required
def attendance_page(request):
    user = request.profile; today = timezone.localdate(); now = timezone.localtime().time().replace(microsecond=0)
    record = Attendance.objects.filter(user=user, date=today).first()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'checkin':
            if record: messages.warning(request, 'You already checked in today.')
            else:
                status = 'Late' if now.hour >= 10 else 'Present'
                Attendance.objects.create(user=user, date=today, checkIn=now, status=status, work_mode=request.POST.get('work_mode','Office'), notes=request.POST.get('notes',''))
                messages.success(request, 'Checked in successfully.')
        elif not record: messages.error(request, 'Please check in first.')
        elif action == 'checkout':
            record.checkOut = now; record.notes = request.POST.get('notes', record.notes); record.save(); messages.success(request, 'Checked out successfully.')
        return redirect('attendance')
    records = Attendance.objects.filter(user=user).order_by('-date')[:30]
    return render(request, 'ems/attendance.html', base_context(request, record=record, records=records))


@role_required('admin','hr','manager')
def attendance_reports(request):
    records = Attendance.objects.select_related('user','user__department').order_by('-date')
    if request.profile.role == 'manager': records = records.filter(user__manager=request.profile)
    return render(request, 'ems/attendance_reports.html', base_context(request, records=records))


@login_required
def leave_apply(request):
    user = request.profile
    if request.method == 'POST':
        from_date = datetime.strptime(request.POST.get('fromDate'), '%Y-%m-%d').date(); to_date = datetime.strptime(request.POST.get('toDate'), '%Y-%m-%d').date(); duration = (to_date - from_date).days + 1
        if duration <= 0: messages.error(request, 'Invalid leave date range.')
        elif user.leaveBalance < duration: messages.error(request, 'Insufficient leave balance.')
        else:
            LeaveRequest.objects.create(user=user, fromDate=from_date, toDate=to_date, reason=request.POST.get('reason',''), leaveType=request.POST.get('leaveType','Casual Leave'), duration=duration)
            messages.success(request, 'Leave request submitted.'); return redirect('leaves')
    leaves = LeaveRequest.objects.filter(user=user).order_by('-createdAt')
    return render(request, 'ems/leave_apply.html', base_context(request, leaves=leaves))


@login_required
def leaves_list(request):
    user = request.profile
    leaves = LeaveRequest.objects.select_related('user','user__manager','approver').order_by('-createdAt')
    if user.role == 'employee': leaves = leaves.filter(user=user)
    elif user.role == 'manager': leaves = leaves.filter(Q(user__manager=user) | Q(user=user))
    leaves = list(leaves)
    for leave in leaves:
        leave.can_decide = can_approve_leave(user, leave) and leave.status == 'pending'
    return render(request, 'ems/leaves.html', base_context(request, leaves=leaves))


@role_required('admin','hr','manager')
def leave_update(request, pk):
    leave = get_object_or_404(LeaveRequest.objects.select_related('user', 'user__manager'), pk=pk)
    if not can_approve_leave(request.profile, leave):
        messages.error(request, 'You are not allowed to approve this leave request.')
        return redirect('leaves')
    if request.method == 'POST' and leave.status == 'pending':
        new_status = request.POST.get('status')
        if new_status not in ['approved', 'rejected']:
            messages.error(request, 'Invalid leave decision.')
            return redirect('leaves')
        leave.status = new_status
        leave.approver = request.profile
        leave.approver_comments = request.POST.get('approver_comments','')
        if hasattr(leave, 'approved_on'):
            leave.approved_on = timezone.now()
        leave.save()
        if leave.status == 'approved':
            lb, _ = LeaveBalance.objects.get_or_create(employee=leave.user, year=timezone.localdate().year, leave_type=leave.leaveType, defaults={'opening_balance': leave.user.leaveBalance})
            lb.used += leave.duration
            lb.save()
            leave.user.leaveBalance = sum(x.available for x in leave.user.leave_balances.filter(year=timezone.localdate().year))
            leave.user.leaveTakenThisYear += leave.duration
            leave.user.save(update_fields=['leaveBalance','leaveTakenThisYear'])
        create_notification(leave.user, f'Leave {leave.status.title()}', f'Your {leave.leaveType} request from {leave.fromDate} to {leave.toDate} was {leave.status}.')
        messages.success(request, f'Leave {leave.status}.'); log(request.profile.username, 'Leave decision', f'{leave.user.username}: {leave.status}')
    return redirect('leaves')


@role_required('admin','hr')
def payroll_assign(request):
    users = UserProfile.objects.exclude(role='admin').order_by('full_name')
    if request.method == 'POST':
        employee = get_object_or_404(UserProfile, pk=request.POST.get('employee'))
        Payroll.objects.create(employee=employee, month=request.POST.get('month',''), basic=Decimal(request.POST.get('basic') or '0'), hra=Decimal(request.POST.get('hra') or '0'), allowance=Decimal(request.POST.get('allowance') or '0'), deductions=Decimal(request.POST.get('deductions') or '0'), status=request.POST.get('status','Draft'))
        messages.success(request, 'Payroll record saved.'); log(request.profile.username, 'Processed payroll', employee.username); return redirect('payroll')
    return render(request, 'ems/payroll_form.html', base_context(request, users=users))


@login_required
def payroll_list(request):
    payrolls = Payroll.objects.select_related('employee').order_by('-createdAt')
    if request.profile.role == 'employee': payrolls = payrolls.filter(employee=request.profile)
    elif request.profile.role == 'manager': payrolls = payrolls.filter(employee__manager=request.profile)
    return render(request, 'ems/payroll.html', base_context(request, payrolls=payrolls))


@login_required
def performance(request):
    user = request.profile
    reviews = PerformanceReview.objects.select_related('employee','reviewer').order_by('-createdAt')
    employees = managed_employee_queryset(user, include_self=(user.role != 'manager')).exclude(role='admin').order_by('full_name')
    if user.role == 'employee':
        reviews = reviews.filter(employee=user); employees = employees.filter(id=user.id)
    elif user.role == 'manager':
        reviews = reviews.filter(employee__manager=user); employees = employees.filter(role='employee')
    if request.method == 'POST' and user.role in ['admin','hr','manager']:
        emp = get_object_or_404(employees, pk=request.POST.get('employee'))
        PerformanceReview.objects.create(employee=emp, reviewer=user, period=request.POST.get('period',''), goals_score=int(request.POST.get('goals_score') or 0), quality_score=int(request.POST.get('quality_score') or 0), teamwork_score=int(request.POST.get('teamwork_score') or 0), punctuality_score=int(request.POST.get('punctuality_score') or 0), comments=request.POST.get('comments',''))
        messages.success(request, 'Performance review submitted.'); return redirect('performance')
    tasks = Task.objects.all()
    if user.role == 'employee': tasks = tasks.filter(assignee=user)
    elif user.role == 'manager': tasks = tasks.filter(assignee__manager=user)
    completed = tasks.filter(status='Approved').count(); total = tasks.count(); score = round((completed / total) * 100, 1) if total else 0
    return render(request, 'ems/performance.html', base_context(request, reviews=reviews, employees=employees, total=total, completed=completed, score=score))


@role_required('admin','hr')
def announcements(request):
    if request.method == 'POST':
        Announcement.objects.create(title=request.POST.get('title',''), message=request.POST.get('message',''), audience=request.POST.get('audience','All'), created_by=request.profile)
        messages.success(request, 'Announcement published.'); return redirect('announcements')
    return render(request, 'ems/announcements.html', base_context(request, announcements=Announcement.objects.order_by('-createdAt')))


@role_required('admin','hr')
def audit_logs(request):
    return render(request, 'ems/audit_logs.html', base_context(request, logs=AuditLog.objects.order_by('-createdAt')[:200]))

@login_required
def notifications(request):
    notes = Notification.objects.filter(recipient=request.profile).order_by('-createdAt')[:100]
    if request.method == 'POST':
        notes.update(status='read')
        messages.success(request, 'Notifications marked as read.')
        return redirect('notifications')
    return render(request, 'ems/notifications.html', base_context(request, notifications=notes))


@login_required
def documents(request):
    user = request.profile
    if user.role in ['admin', 'hr']:
        employees = UserProfile.objects.order_by('full_name')
        docs = EmployeeDocument.objects.select_related('employee','uploaded_by').order_by('-createdAt')
    elif user.role == 'manager':
        employees = managed_employee_queryset(user).filter(role='employee')
        docs = EmployeeDocument.objects.select_related('employee','uploaded_by').filter(employee__manager=user).order_by('-createdAt')
    else:
        employees = UserProfile.objects.filter(id=user.id)
        docs = EmployeeDocument.objects.select_related('employee','uploaded_by').filter(employee=user).order_by('-createdAt')

    if request.method == 'POST':
        employee = get_object_or_404(employees, pk=request.POST.get('employee'))
        file = request.FILES.get('file')
        if not file:
            messages.error(request, 'Please choose a document file.')
        else:
            EmployeeDocument.objects.create(
                employee=employee,
                document_type=request.POST.get('document_type','Other'),
                title=request.POST.get('title','').strip() or file.name,
                file=file,
                uploaded_by=user,
                is_confidential=bool(request.POST.get('is_confidential')),
            )
            create_notification(employee, 'Document uploaded', f'{user.display_name} uploaded a document: {file.name}')
            messages.success(request, 'Document uploaded.')
            return redirect('documents')
    return render(request, 'ems/documents.html', base_context(request, documents=docs, employees=employees))


@role_required('admin','hr')
def holidays(request):
    if request.method == 'POST':
        Holiday.objects.update_or_create(
            date=request.POST.get('date'),
            defaults={
                'name': request.POST.get('name','').strip(),
                'location': request.POST.get('location','All').strip() or 'All',
                'is_optional': bool(request.POST.get('is_optional')),
            }
        )
        messages.success(request, 'Holiday saved.')
        return redirect('holidays')
    return render(request, 'ems/holidays.html', base_context(request, holidays=Holiday.objects.order_by('date')))


@login_required
def leave_balances(request):
    user = request.profile
    balances = LeaveBalance.objects.select_related('employee').order_by('employee__userId','leave_type')
    employees = managed_employee_queryset(user, include_self=True)
    if user.role == 'employee':
        balances = balances.filter(employee=user)
    elif user.role == 'manager':
        balances = balances.filter(employee__manager=user)
    if request.method == 'POST' and user.role in ['admin','hr']:
        employee = get_object_or_404(UserProfile, pk=request.POST.get('employee'))
        lb, _ = LeaveBalance.objects.get_or_create(
            employee=employee,
            year=int(request.POST.get('year') or timezone.localdate().year),
            leave_type=request.POST.get('leave_type','Casual Leave'),
            defaults={'opening_balance': 0}
        )
        lb.opening_balance = int(request.POST.get('opening_balance') or lb.opening_balance)
        lb.credited = int(request.POST.get('credited') or 0)
        lb.adjusted = int(request.POST.get('adjusted') or 0)
        lb.save()
        employee.leaveBalance = sum(x.available for x in employee.leave_balances.filter(year=lb.year))
        employee.save(update_fields=['leaveBalance'])
        messages.success(request, 'Leave balance updated.')
        return redirect('leave_balances')
    return render(request, 'ems/leave_balances.html', base_context(request, balances=balances, employees=employees))


@role_required('admin','hr','manager')
def reports(request):
    user = request.profile
    report_type = request.GET.get('type', 'employees')
    export = request.GET.get('export') == 'csv'

    if report_type == 'attendance':
        rows = Attendance.objects.select_related('user','user__department').order_by('-date')
        headers = ['Employee ID','Name','Department','Date','Check In','Check Out','Status','Mode']
        if user.role == 'manager': rows = rows.filter(user__manager=user)
        data = [[r.user.userId, r.user.display_name, r.user.department.name if r.user.department else '', r.date, r.checkIn or '', r.checkOut or '', r.status, r.work_mode] for r in rows]
    elif report_type == 'leave':
        rows = LeaveRequest.objects.select_related('user','approver').order_by('-createdAt')
        headers = ['Employee ID','Name','Type','From','To','Days','Status','Approver']
        if user.role == 'manager': rows = rows.filter(user__manager=user)
        data = [[r.user.userId, r.user.display_name, r.leaveType, r.fromDate, r.toDate, r.duration, r.status, r.approver.display_name if r.approver else ''] for r in rows]
    elif report_type == 'payroll':
        rows = Payroll.objects.select_related('employee').order_by('-createdAt')
        headers = ['Employee ID','Name','Month','Basic','HRA','Allowance','Deductions','Net Pay','Status']
        if user.role == 'manager': rows = rows.filter(employee__manager=user)
        data = [[r.employee.userId, r.employee.display_name, r.month, r.basic, r.hra, r.allowance, r.deductions, r.net_pay, r.status] for r in rows]
    else:
        rows = managed_employee_queryset(user, include_self=True)
        headers = ['Employee ID','Name','Email','Role','Department','Manager','Status','Designation']
        data = [[r.userId, r.display_name, r.email, r.role, r.department.name if r.department else '', r.manager.display_name if r.manager else '', r.employment_status, r.designation] for r in rows]

    if export:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{report_type}_report.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(data)
        return response

    return render(request, 'ems/reports.html', base_context(request, report_type=report_type, headers=headers, data=data[:200]))


@login_required
def change_password(request):
    user = request.profile
    if request.method == 'POST':
        current = request.POST.get('current_password','')
        new = request.POST.get('new_password','')
        confirm = request.POST.get('confirm_password','')
        if not password_matches(current, user.password):
            messages.error(request, 'Current password is incorrect.')
        elif len(new) < 8:
            messages.error(request, 'New password must be at least 8 characters.')
        elif new != confirm:
            messages.error(request, 'New passwords do not match.')
        else:
            user.password = make_password(new)
            user.must_change_password = False
            user.save(update_fields=['password','must_change_password'])
            messages.success(request, 'Password changed successfully.')
            return redirect('dashboard')
    return render(request, 'ems/change_password.html', base_context(request))
