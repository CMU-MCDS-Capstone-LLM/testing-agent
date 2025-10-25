from dataclasses import dataclass
from datetime import datetime
from marshmallow import Schema, fields, post_load

@dataclass
class Note:
    title: str = ""
    content: str = ""
    date: datetime = None
    
    @property
    def date_string(self):
        if self.date:
            return self.date.strftime("%Y-%m-%d")
        return datetime.now().strftime("%Y-%m-%d")
    
    def to_markdown_string(self):
        if self.title:
            return f"# {self.title}\n{self.content}"
        return self.content
    
    def is_empty(self):
        return not (self.title or self.content)

class NoteSchema(Schema):
    title = fields.Str(allow_none=True, default="")
    content = fields.Str(allow_none=True, default="")
    date = fields.DateTime(allow_none=True)
    
    @post_load
    def make_note(self, data, **kwargs):
        return Note(**data)
