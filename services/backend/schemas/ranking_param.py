
from pydantic import BaseModel

from shared.database import RankingParam


class RankingParamSchema(BaseModel):
    name: str
    value: float

    @classmethod
    def from_db(
        cls,
        param: RankingParam
    ) -> 'RankingParamSchema':
        return cls(name=param.name, value=param.value)

    @classmethod
    def from_db_list(
        cls,
        params: list[RankingParam]
    ) -> list['RankingParamSchema']:
        return [cls.from_db(param) for param in params]
    
class EditRankingParamSchema(BaseModel):
    value: float
