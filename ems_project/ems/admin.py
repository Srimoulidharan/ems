from django.contrib import admin
from .models import (
    Announcement, Attendance, AuditLog, Department, EmployeeDocument, Holiday,
    LeaveBalance, LeaveRequest, Notification, Payroll, PerformanceReview, Shift,
    Task, UserProfile
)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('userId', 'display_name', 'email', 'role', 'department', 'manager', 'employment_status')
    list_filter = ('role', 'employment_status', 'department')
    search_fields = ('userId', 'username', 'full_name', 'email', 'designation')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'leaveType', 'fromDate', 'toDate', 'duration', 'status', 'approver')
    list_filter = ('status', 'leaveType')

for model in [Department, Task, Attendance, Payroll, PerformanceReview, Announcement, AuditLog, Holiday, LeaveBalance, EmployeeDocument, Notification, Shift]:
    try:
        admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass
