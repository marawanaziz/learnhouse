"""Per-program cohort provisioning templates — the workbook + weekly discussion
prompts that get auto-seeded into every new cohort so a facilitator never starts
from a blank community.

These are DEFAULTS: create_cohort copies them onto the cohort at creation, and
they're fully editable per-cohort afterward (PUT /bbu/cohorts/{id} with
workbook_url / weekly_prompts). Prompts are dripped into the cohort's community
one per week by the lifecycle scheduler (service.post_due_prompts), pinned as
Announcements, scheduled off the cohort's start_date.

`week` is 1-indexed; its post date = start_date + (week-1)*7 days.
"""

# Program → default workbook link (override per-cohort as real workbooks are made).
WORKBOOK_URLS = {
    "doula": "",   # set to the cohort workbook URL; blank = none until provided
    "agency": "",
}

# Program → ordered weekly prompts. Written in BBU's supportive, professional
# voice; each seeds that week's reflection / discussion in the cohort community.
WEEKLY_PROMPTS = {
    "doula": [
        {"week": 1, "emoji": "\U0001F331", "title": "Week 1 — Why this work",
         "content": "Welcome to your mentorship cohort! To kick us off: what drew you to doula work, and what does the doula you want to become look like six weeks from now? Share one hope and one worry you're carrying into this program."},
        {"week": 2, "emoji": "\U0001F91D", "title": "Week 2 — Presence & the client relationship",
         "content": "Think back to a time someone made you feel truly held — supported without being fixed. What did they do? This week, notice how you show up in your own client interactions. Post one small way you practiced presence."},
        {"week": 3, "emoji": "\U0001F9ED", "title": "Week 3 — Scope, boundaries & referrals",
         "content": "Where does a doula's role end and another provider's begin? Describe a real or imagined moment where you'd need to hold your scope and refer out. How would you word it with warmth and confidence?"},
        {"week": 4, "emoji": "\U0001F4AC", "title": "Week 4 — Hard conversations",
         "content": "Advocacy sometimes means navigating tension in the room. Share a scenario you find intimidating (a tense provider, a divided family, a plan that shifts fast). What language or grounding technique could help you stay centered?"},
        {"week": 5, "emoji": "\U0001F4BC", "title": "Week 5 — Building a sustainable practice",
         "content": "Burnout is real in this field. What does a sustainable week look like for you — on-call limits, pricing, backup, rest? Post one boundary you're going to put in writing for your business."},
        {"week": 6, "emoji": "\U0001F3AF", "title": "Week 6 — Integration & next steps",
         "content": "Look back at your Week 1 post. What shifted? Name one thing you're proud of, one skill you'll keep growing, and your very next concrete step after this cohort. Celebrate someone else's growth in the comments."},
    ],
    "agency": [
        {"week": 1, "emoji": "\U0001F331", "title": "Week 1 — Your agency vision",
         "content": "Welcome! Paint the picture: what does your agency look like in 12 months? Who do you serve, how many doulas, what feeling do clients walk away with? Share your vision and the single biggest obstacle between you and it."},
        {"week": 2, "emoji": "\U0001F4CA", "title": "Week 2 — Offers & pricing",
         "content": "Map your current (or planned) service offers and price points. Where are you undercharging? Post one offer you want feedback on and the outcome it delivers for the client."},
        {"week": 3, "emoji": "\U0001F465", "title": "Week 3 — Hiring & contractor vs. employee",
         "content": "What kind of doula do you want on your team, and how will you find them? Share your thinking on contractor vs. employee for your model, and one thing you're unsure about."},
        {"week": 4, "emoji": "\U0001F4DD", "title": "Week 4 — Systems & client journey",
         "content": "Trace a client from inquiry to postpartum wrap-up. Where does it break or feel manual today? Post the one system (intake, scheduling, matching, billing) you most want to automate first."},
        {"week": 5, "emoji": "\U0001F4E3", "title": "Week 5 — Marketing that fits you",
         "content": "Which marketing channel actually feels sustainable for you (referrals, community, content, partnerships)? Share your best-performing source of clients and one channel you want to test."},
        {"week": 6, "emoji": "\U0001F680", "title": "Week 6 — 90-day agency plan",
         "content": "Bring it together: what are your three priorities for the next 90 days? Post them here so the group can hold you accountable — and comment on one peer's plan with an idea or offer of help."},
    ],
}


def workbook_for(program: str) -> str:
    return WORKBOOK_URLS.get(program, "")


def prompts_for(program: str) -> list:
    """Fresh copy of the program's weekly prompts (posted_at unset)."""
    base = WEEKLY_PROMPTS.get(program, [])
    return [{**p, "posted_at": ""} for p in base]
