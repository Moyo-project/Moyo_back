from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, constr
 

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    nickname:str
    password: str
    profile_image_url: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    nickname: str
    profile_image_url: Optional[str] = None

    class Config:
        from_attributes = True  # SQLAlchemy 모델 -> Pydantic 변환 허용

# 🔥 회원가입 응답을 프론트 기대에 맞게 변경
class SignupOut(BaseModel):
    access_token: str
    user: UserOut

class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    
class EmailRequest(BaseModel):
    email: EmailStr
    
class EmailConfirm(BaseModel):
    email: EmailStr
    code: str

NicknameStr = Annotated[str, StringConstraints(min_length=1, max_length=30)]

class NicknameUpdate(BaseModel):
    nickname: NicknameStr

class PasswordReset(BaseModel):
    email: EmailStr
    new_password: str

class PasswordChange(BaseModel):
    current_password: str
    new_password: str