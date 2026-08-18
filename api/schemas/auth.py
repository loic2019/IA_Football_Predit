from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""


class UserOut(BaseModel):
    uid: str
    email: EmailStr
    display_name: str = ""
    role: str
