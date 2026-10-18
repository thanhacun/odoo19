def sample_payload():
    """Payload in the format n8n sends (same as Odoo 12)."""
    customers = [
        {'partner_id': [501, 'Nippon Shokken'], 'name': 'Nippon Shokken Vietnam', 'code': 'C501', 'email': 'a@example.com'},
        {'partner_id': 502, 'name': 'Taisei Corporation', 'code': 'C502', 'email': False},
    ]
    jobs = [
        {
            'id': 9001, 'code': 'HM11-26-0004', 'name': 'Nippon Shokken New Factory',
            'general_expense': False, 'owner_id': 501, 'partner_id': [502, 'Taisei'],
            'date_start': '2026-01-15', 'actual_completion_date': 'False', 'kickoff_meeting_date': False,
            'state': 'doing', 'role_logins': {'user_id': 'kdvn_test_pm', 'manager_id': 'nobody_here'},
        },
        {
            'id': 9002, 'code': 'HM11-26-1004', 'name': 'Taisei Square Hanoi',
            'general_expense': True, 'owner_id': False, 'partner_id': 502,
            'date_start': False, 'state': 'done', 'kom_peak_from': '2026-03-01', 'kom_peak_to': '2026-04-30',
        },
    ]
    budgets = [
        {'id': 7001, 'budget_code': 'B01', 'name': 'Materials', 'balance_amt': 45000000, 'job_id': [9001, 'HM11-26-0004']},
        {'id': 7002, 'budget_code': 'B02', 'name': False, 'balance_amt': 1000, 'job_id': 9001},
        {'id': 7003, 'budget_code': 'B03', 'name': 'Unknown job', 'job_id': 1234},
    ]
    return jobs, budgets, customers
