from django.db import models
from django.utils import timezone

ROLE_CHOICES = [('admin', 'Admin'), ('hr', 'HR'), ('manager', 'Manager'), ('employee', 'Employee')]
EMPLOYMENT_STATUS = [('Active', 'Active'), ('On Notice', 'On Notice'), ('Inactive', 'Inactive')]
TASK_STATUS = [('Todo', 'Todo'), ('In Progress', 'In Progress'), ('In Review', 'In Review'), ('Approved', 'Approved'), ('Rejected', 'Rejected')]
LEAVE_STATUS = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
PAYROLL_STATUS = [('Draft', 'Draft'), ('Processed', 'Processed'), ('Paid', 'Paid')]
ATTENDANCE_STATUS = [('Present', 'Present'), ('Late', 'Late'), ('Half Day', 'Half Day'), ('Absent', 'Absent'), ('WFH', 'WFH')]

DOCUMENT_TYPES = [('ID Proof','ID Proof'),('Resume','Resume'),('Offer Letter','Offer Letter'),('Certificate','Certificate'),('Other','Other')]
NOTIFICATION_STATUS = [('unread','Unread'),('read','Read')]


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True)
    head = models.CharField(max_length=120, blank=True)
    location = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    userId = models.CharField('Employee ID', max_length=80, unique=True)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    full_name = models.CharField(max_length=160, blank=True)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='employees')
    manager = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='team_members')
    date_joined = models.DateField(default=timezone.localdate)
    employment_status = models.CharField(max_length=30, choices=EMPLOYMENT_STATUS, default='Active')
    work_location = models.CharField(max_length=120, default='Head Office')
    experience = models.IntegerField(default=0)
    skillset = models.JSONField(default=list, blank=True)
    leaveBalance = models.IntegerField(default=12)
    leaveTakenThisYear = models.IntegerField(default=0)
    salary_ctc = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_name = models.CharField(max_length=120, blank=True)
    account_last4 = models.CharField(max_length=4, blank=True)
    projectWorkingOn = models.CharField(max_length=200, blank=True)
    emergency_contact = models.CharField(max_length=120, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    must_change_password = models.BooleanField(default=False)
    updatedAt = models.DateTimeField(auto_now=True)

    @property
    def display_name(self):
        return self.full_name or self.username

    def __str__(self):
        return f'{self.display_name} ({self.userId})'


class Task(models.Model):
    taskName = models.CharField(max_length=200)
    taskDescription = models.TextField()
    priority = models.CharField(max_length=20, choices=[('Low','Low'),('Medium','Medium'),('High','High'),('Critical','Critical')], default='Medium')
    deadline = models.DateField(null=True, blank=True)
    assignee = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='tasks')
    assigned_by = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, null=True, related_name='assigned_tasks')
    status = models.CharField(max_length=40, choices=TASK_STATUS, default='Todo')
    progress = models.IntegerField(default=0)
    submittedWork = models.TextField(null=True, blank=True)
    manager_feedback = models.TextField(blank=True)
    submissionDate = models.DateTimeField(null=True, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.taskName


class Attendance(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='attendance')
    date = models.DateField(default=timezone.localdate)
    checkIn = models.TimeField(null=True, blank=True)
    checkOut = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=ATTENDANCE_STATUS, default='Present')
    work_mode = models.CharField(max_length=30, choices=[('Office','Office'),('Remote','Remote'),('Hybrid','Hybrid')], default='Office')
    notes = models.TextField(blank=True)
    breaks = models.JSONField(default=list, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date')


class LeaveRequest(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='leaves')
    fromDate = models.DateField()
    toDate = models.DateField()
    reason = models.TextField(blank=True)
    leaveType = models.CharField(max_length=80, default='Casual Leave')
    status = models.CharField(max_length=20, choices=LEAVE_STATUS, default='pending')
    duration = models.IntegerField(default=0)
    approver = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_leaves')
    approved_on = models.DateTimeField(null=True, blank=True)
    approver_comments = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)


class Payroll(models.Model):
    employee = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='payrolls')
    month = models.CharField(max_length=50)
    basic = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=50, choices=PAYROLL_STATUS, default='Draft')
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.net_pay = (self.basic or 0) + (self.hra or 0) + (self.allowance or 0) - (self.deductions or 0)
        super().save(*args, **kwargs)


class PerformanceReview(models.Model):
    employee = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='performance_reviews')
    reviewer = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviews_given')
    period = models.CharField(max_length=80)
    goals_score = models.IntegerField(default=0)
    quality_score = models.IntegerField(default=0)
    teamwork_score = models.IntegerField(default=0)
    punctuality_score = models.IntegerField(default=0)
    comments = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)

    @property
    def overall_score(self):
        return round((self.goals_score + self.quality_score + self.teamwork_score + self.punctuality_score) / 4, 1)


class Announcement(models.Model):
    title = models.CharField(max_length=180)
    message = models.TextField()
    audience = models.CharField(max_length=40, choices=[('All','All'),('Managers','Managers'),('Employees','Employees')], default='All')
    created_by = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.SET_NULL)
    createdAt = models.DateTimeField(auto_now_add=True)


class AuditLog(models.Model):
    actor = models.CharField(max_length=120)
    action = models.CharField(max_length=200)
    details = models.TextField(blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)


class Holiday(models.Model):
    name = models.CharField(max_length=160)
    date = models.DateField(unique=True)
    location = models.CharField(max_length=120, default='All')
    is_optional = models.BooleanField(default=False)
    createdAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.name} - {self.date}'


class LeaveBalance(models.Model):
    employee = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='leave_balances')
    year = models.IntegerField(default=timezone.localdate().year)
    leave_type = models.CharField(max_length=80, default='Casual Leave')
    opening_balance = models.IntegerField(default=12)
    credited = models.IntegerField(default=0)
    used = models.IntegerField(default=0)
    adjusted = models.IntegerField(default=0)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'year', 'leave_type')

    @property
    def available(self):
        return max(0, self.opening_balance + self.credited + self.adjusted - self.used)


class EmployeeDocument(models.Model):
    employee = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=80, choices=DOCUMENT_TYPES, default='Other')
    title = models.CharField(max_length=180)
    file = models.FileField(upload_to='employee_documents/')
    uploaded_by = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name='uploaded_documents')
    is_confidential = models.BooleanField(default=False)
    createdAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Notification(models.Model):
    recipient = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=180)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=NOTIFICATION_STATUS, default='unread')
    createdAt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-createdAt']


class Shift(models.Model):
    name = models.CharField(max_length=120, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.IntegerField(default=15)
    createdAt = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
