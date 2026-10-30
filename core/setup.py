"""
Default configuration for a new church: roles, a church-oriented chart of
accounts, common funds and payroll items. Safe to run more than once; existing
records are left untouched.
"""

from decimal import Decimal

from django.contrib.auth.models import Group
from django.db import transaction

from .models import ChurchProfile
from .permissions import ROLES

# number, name, type, subtype, function, system_code
CHART_OF_ACCOUNTS = [
    # Assets
    ("1010", "Operating Checking", "asset", "bank", "", None),
    ("1020", "Savings / Reserve Account", "asset", "bank", "", None),
    ("1050", "Petty Cash", "asset", "cash", "", None),
    ("1100", "Accounts Receivable", "asset", "receivable", "", None),
    ("1200", "Prepaid Expenses", "asset", "other_current_asset", "", None),
    ("1300", "Investments", "asset", "investment", "", None),
    ("1500", "Land", "asset", "fixed_asset", "", None),
    ("1510", "Buildings & Improvements", "asset", "fixed_asset", "", None),
    ("1520", "Furniture & Equipment", "asset", "fixed_asset", "", None),
    ("1530", "Sound, Video & Instruments", "asset", "fixed_asset", "", None),
    ("1540", "Vehicles", "asset", "fixed_asset", "", None),
    ("1590", "Accumulated Depreciation", "asset", "accumulated_depreciation", "", "accumulated_depreciation"),
    # Liabilities
    ("2000", "Accounts Payable", "liability", "payable", "", "accounts_payable"),
    ("2050", "Church Credit Card", "liability", "credit_card", "", None),
    ("2100", "Payroll Taxes Payable", "liability", "payroll_liability", "", None),
    ("2110", "Income Tax Withholding Payable", "liability", "payroll_liability", "", None),
    ("2120", "Retirement Contributions Payable", "liability", "payroll_liability", "", None),
    ("2130", "Health Insurance Payable", "liability", "payroll_liability", "", None),
    ("2300", "Accrued Expenses", "liability", "other_current_liability", "", None),
    ("2500", "Mortgage / Notes Payable", "liability", "long_term_liability", "", None),
    # Net assets
    ("3000", "Net Assets Without Donor Restrictions", "equity", "net_assets", "", "net_assets_unrestricted"),
    ("3100", "Net Assets With Donor Restrictions", "equity", "net_assets", "", "net_assets_restricted"),
    ("3900", "Interfund Transfers", "equity", "transfers", "", "interfund_transfers"),
    # Income
    ("4000", "Tithes", "income", "contributions", "", None),
    ("4010", "General Offerings", "income", "contributions", "", None),
    ("4020", "Designated Gifts", "income", "contributions", "", None),
    ("4030", "Building Fund Contributions", "income", "contributions", "", None),
    ("4040", "Missions Contributions", "income", "contributions", "", None),
    ("4050", "Benevolence Contributions", "income", "contributions", "", None),
    ("4060", "Special Offerings", "income", "contributions", "", None),
    ("4100", "Fundraising & Event Income", "income", "program_income", "", None),
    ("4110", "Ministry Program Fees", "income", "program_income", "", None),
    ("4200", "Facility Rental Income", "income", "other_income", "", None),
    ("4300", "Interest & Dividend Income", "income", "other_income", "", None),
    ("4400", "Grants", "income", "other_income", "", None),
    ("4800", "Gain / Loss on Asset Disposal", "income", "other_income", "", "asset_disposal"),
    ("4900", "Miscellaneous Income", "income", "other_income", "", None),
    # Personnel
    ("5000", "Pastoral Salaries", "expense", "personnel", "program", None),
    ("5010", "Staff Salaries & Wages", "expense", "personnel", "management", None),
    ("5020", "Clergy Housing Allowance", "expense", "personnel", "program", None),
    ("5030", "Employer Payroll Taxes", "expense", "personnel", "management", None),
    ("5040", "Employee Benefits", "expense", "personnel", "management", None),
    ("5050", "Contract Labor & Guest Speakers", "expense", "personnel", "program", None),
    # Facilities
    ("6000", "Rent / Mortgage Interest", "expense", "facilities", "management", None),
    ("6010", "Utilities", "expense", "facilities", "management", None),
    ("6020", "Repairs & Maintenance", "expense", "facilities", "management", None),
    ("6030", "Janitorial & Supplies", "expense", "facilities", "management", None),
    ("6040", "Property Insurance", "expense", "facilities", "management", None),
    ("6050", "Security & Alarm", "expense", "facilities", "management", None),
    # Ministries
    ("7000", "Worship & Music", "expense", "ministry", "program", None),
    ("7010", "Children's Ministry", "expense", "ministry", "program", None),
    ("7020", "Youth Ministry", "expense", "ministry", "program", None),
    ("7030", "Adult Education & Discipleship", "expense", "ministry", "program", None),
    ("7040", "Outreach & Evangelism", "expense", "ministry", "program", None),
    ("7050", "Events & Fellowship", "expense", "ministry", "program", None),
    ("7060", "Pastoral Care & Hospitality", "expense", "ministry", "program", None),
    ("7100", "Missions Support", "expense", "missions", "program", None),
    ("7110", "Benevolence Assistance", "expense", "missions", "program", None),
    # Administration
    ("8000", "Office Supplies", "expense", "administration", "management", None),
    ("8010", "Postage & Printing", "expense", "administration", "management", None),
    ("8020", "Telephone & Internet", "expense", "administration", "management", None),
    ("8030", "Software & Technology", "expense", "administration", "management", None),
    ("8040", "Bank & Merchant Fees", "expense", "administration", "management", None),
    ("8050", "Accounting & Legal Fees", "expense", "administration", "management", None),
    ("8060", "Conferences & Training", "expense", "administration", "program", None),
    ("8070", "Travel & Mileage", "expense", "administration", "program", None),
    ("8080", "Denominational Dues", "expense", "administration", "management", None),
    ("8090", "Advertising & Communications", "expense", "administration", "fundraising", None),
    ("8100", "Depreciation Expense", "expense", "other_expense", "management", "depreciation_expense"),
    ("8110", "Interest Expense", "expense", "other_expense", "management", None),
    ("8900", "Miscellaneous Expense", "expense", "other_expense", "management", None),
]

# code, name, restriction, default income account, is_default, description
FUNDS = [
    ("GEN", "General Fund", "unrestricted", "4000", True, "Everyday operations: tithes and undesignated offerings."),
    ("BLD", "Building Fund", "restricted", "4030", False, "Gifts designated for buildings, renovations and major repairs."),
    ("MIS", "Missions Fund", "restricted", "4040", False, "Gifts designated for missionaries and mission partners."),
    ("BEN", "Benevolence Fund", "restricted", "4050", False, "Gifts designated to help people in need."),
    ("YTH", "Youth Ministry Fund", "designated", "4020", False, "Board-designated savings for youth camps and trips."),
]

# code, name, kind, calculation, default_amount, expense acct, liability acct, in_wage_base, sort
PAYROLL_ITEMS = [
    ("REGULAR", "Regular Pay", "earning", "fixed", "0", None, None, True, 10),
    ("HOUSING", "Housing Allowance", "earning", "fixed", "0", "5020", None, False, 20),
    (None, "Bonus / Other Pay", "earning", "fixed", "0", None, None, True, 30),
    (None, "Income Tax Withholding", "deduction", "percent", "10", None, "2110", True, 40),
    (None, "Social Security – Employee", "deduction", "percent", "7.65", None, "2100", True, 50),
    (None, "Retirement – Employee", "deduction", "percent", "5", None, "2120", True, 60),
    (None, "Health Insurance – Employee Share", "deduction", "fixed", "0", None, "2130", True, 70),
    (None, "Social Security – Employer", "employer", "percent", "7.65", "5030", "2100", True, 80),
    (None, "Retirement – Employer Match", "employer", "percent", "3", "5040", "2120", True, 90),
]


@transaction.atomic
def setup_church(church_name=None, currency_symbol=None, currency_code=None, fiscal_start_month=None):
    from ledger.models import Account, Fund
    from payroll.models import PayrollItem

    profile = ChurchProfile.get()
    changed = False
    for attr, value in [("name", church_name), ("currency_symbol", currency_symbol),
                        ("currency_code", currency_code), ("fiscal_year_start_month", fiscal_start_month)]:
        if value:
            setattr(profile, attr, value)
            changed = True
    if changed:
        profile.save()

    for role in ROLES:
        Group.objects.get_or_create(name=role)

    accounts = {}
    for number, name, type_, subtype, function, system_code in CHART_OF_ACCOUNTS:
        existing = Account.objects.filter(system_code=system_code).first() if system_code else None
        account = existing or Account.objects.filter(number=number).first()
        if account is None:
            account = Account.objects.create(
                number=number, name=name, type=type_, subtype=subtype, function=function, system_code=system_code,
            )
        elif system_code and not account.system_code:
            account.system_code = system_code
            account.save(update_fields=["system_code"])
        accounts[number] = account

    for code, name, restriction, income_number, is_default, description in FUNDS:
        if not Fund.objects.filter(code=code).exists():
            Fund.objects.create(
                code=code, name=name, restriction=restriction, is_default=is_default, description=description,
                default_income_account=accounts.get(income_number),
            )

    for code, name, kind, calc, amount, expense, liability, in_base, sort in PAYROLL_ITEMS:
        lookup = {"code": code} if code else {"name": name}
        if not PayrollItem.objects.filter(**lookup).exists():
            PayrollItem.objects.create(
                code=code, name=name, kind=kind, calculation=calc, default_amount=Decimal(amount),
                expense_account=accounts.get(expense) if expense else None,
                liability_account=accounts.get(liability) if liability else None,
                in_wage_base=in_base, sort_order=sort,
            )
    return profile
