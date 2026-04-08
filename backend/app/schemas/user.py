from pydantic import BaseModel, EmailStr


class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_admin: bool
    is_active: bool
    approval_status: str
    show_in_member_lists: bool

    model_config = {"from_attributes": True}
