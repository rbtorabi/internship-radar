from dataclasses import dataclass, field


@dataclass
class Job:
    source: str  # greenhouse | lever | ashby | workday
    company: str
    id: str
    title: str
    url: str
    locations: list[str] = field(default_factory=list)
    remote: bool = False
    posted_at: str | None = None  # ISO timestamp, when the ATS provides one
    intern_flag: bool = False  # the ATS itself marks this as an internship (Ashby/Lever)
    detail: str | None = None  # Workday: URL to fetch full locations from
    job_type: str | None = None  # internship | part_time | full_time | other, when the ATS says
    board: str = ""  # the companies/*.json entry this came from
    age_days: int | None = None  # Workday only gives "Posted 3 Days Ago"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.id}"
