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

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.id}"
