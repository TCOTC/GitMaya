from flask import abort, session
from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased, joinedload, relationship
from utils.utils import query_one_page

from .schema import *

CodeUser = aliased(BindUser)
IMUser = aliased(BindUser)


class TeamMemberWithUser(TeamMember):
    code_user = relationship(
        CodeUser,
        primaryjoin=and_(
            TeamMember.code_user_id == CodeUser.id,
            CodeUser.status == 0,
        ),
        viewonly=True,
    )

    im_user = relationship(
        IMUser,
        primaryjoin=and_(
            TeamMember.im_user_id == IMUser.id,
            IMUser.status == 0,
        ),
        viewonly=True,
    )


class RepoWithUsers(Repo):
    users = relationship(
        CodeUser,
        primaryjoin=and_(
            RepoUser.repo_id == Repo.id,
            RepoUser.status == 0,
        ),
        secondary=RepoUser.__table__,
        secondaryjoin=and_(
            CodeUser.id == RepoUser.bind_user_id,
            CodeUser.status == 0,
        ),
        viewonly=True,
    )

    group = relationship(
        ChatGroup,
        primaryjoin=and_(
            ChatGroup.repo_id == Repo.id,
            ChatGroup.status == 0,
        ),
        viewonly=True,
        uselist=False,
    )


def get_team_list_by_user_id(user_id, page=1, size=100):
    query = (
        db.session.query(Team)
        .filter(
            or_(
                Team.user_id == user_id,  # 管理员
                and_(
                    TeamMember.team_id == Team.id,
                    TeamMember.code_user_id == BindUser.id,  # 属于某个team的员工
                    TeamMember.status == 0,
                    BindUser.user_id == user_id,
                    BindUser.status == 0,
                ),
            ),
            Team.status == 0,
        )
        .group_by(Team.id)
    )
    total = query.count()
    if total == 0:
        return [], 0
    return query_one_page(query, page, size), total


def is_team_admin(team_id, user_id):
    return (
        True
        if db.session.query(Team.id)
        .filter(
            Team.user_id == user_id,
            Team.status == 0,
        )
        .limit(1)
        .scalar()
        else False
    )


def get_team_by_id(team_id, user_id):
    team = (
        db.session.query(Team)
        .filter(
            or_(
                Team.user_id == user_id,  # 管理员
                and_(
                    TeamMember.team_id == Team.id,
                    TeamMember.code_user_id == BindUser.id,  # 属于某个team的员工
                    TeamMember.status == 0,
                    BindUser.user_id == user_id,
                    BindUser.status == 0,
                ),
            ),
            Team.id == team_id,
            Team.status == 0,
        )
        .first()
    )
    if not team:
        return abort(404, "can not found team by id")
    return team


def get_application_info_by_team_id(team_id):
    # TODO
    return (
        db.session.query(CodeApplication)
        .filter(
            CodeApplication.team_id == team_id,
            CodeApplication.status.in_([0, 1]),
        )
        .first(),
        db.session.query(IMApplication)
        .filter(
            IMApplication.team_id == team_id,
            IMApplication.status.in_([0, 1]),
        )
        .first(),
    )


def get_team_member(team_id, user_id, page=1, size=20):
    query = (
        db.session.query(TeamMemberWithUser)
        .options(
            joinedload(TeamMemberWithUser.code_user),
            joinedload(TeamMemberWithUser.im_user),
        )
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.status == 0,
        )
    )
    # admin can get all users in current_team
    if not is_team_admin(team_id, user_id):
        query = query.filter(
            TeamMember.code_user_id == BindUser.id,
            TeamMember.status == 0,
            BindUser.user_id == user_id,
            BindUser.status == 0,
        )
    total = query.count()
    if total == 0:
        return [], 0
    return [_format_member(item) for item in query_one_page(query, page, size)], total


def _format_member(item):
    return {
        "id": item.id,
        "status": item.status,
        "code_user": {
            "id": item.code_user.id,
            "user_id": item.code_user.user_id,
            "name": item.code_user.name,
            "email": item.code_user.email,
            "avatar": item.code_user.avatar,
        }
        if item.code_user
        else None,
        "im_user": {
            "id": item.im_user.id,
            "user_id": item.im_user.user_id,
            "name": item.im_user.name,
            "email": item.im_user.email,
            "avatar": item.im_user.avatar,
        }
        if item.im_user
        else None,
    }


def get_team_repo(team_id, user_id, page=1, size=20):
    query = (
        db.session.query(RepoWithUsers)
        .options(
            joinedload(RepoWithUsers.users),
            joinedload(RepoWithUsers.group),
        )
        .join(
            CodeApplication,
            CodeApplication.id == RepoWithUsers.application_id,
        )
        .filter(
            CodeApplication.team_id == team_id,
            CodeApplication.status == 0,
            RepoWithUsers.status == 0,
        )
    )
    total = query.count()
    if total == 0:
        return [], 0
    return [
        _format_repo_user(item) for item in query_one_page(query, page, size)
    ], total


def _format_repo_user(item):
    return {
        "id": item.id,
        "name": item.name,
        "users": [{"id": i.id, "name": i.name, "avatar": i.avatar} for i in item.users],
        "chat": {
            "id": item.group.id,
            "chat_id": item.group.chat_id,
            "name": item.group.name,
        }
        if item.group
        else None,
    }


def get_im_user_by_team_id(team_id, page=1, size=20):
    query = (
        db.session.query(BindUser)
        .join(
            IMApplication,
            IMApplication.id == BindUser.application_id,
        )
        .filter(
            IMApplication.team_id == team_id,
            IMApplication.status.in_([0, 1]),
            BindUser.status == 0,
        )
    )
    total = query.count()
    if total == 0:
        return [], 0
    return query_one_page(query, page, size), total


def set_team_member(team_id, code_user_id, im_user_id):
    if (
        db.session.query(TeamMember.id)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.im_user_id == im_user_id,
            TeamMember.status == 0,
        )
        .limit(1)
        .scalar()
    ):
        return abort(400, "bind duplicate im user")
    db.session.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.code_user_id == code_user_id,
        TeamMember.status == 0,
    ).update(dict(im_user_id=im_user_id))
    db.session.commit()


def add_team_member(team_id, code_user_id):
    """Add a team member.
    Args:
        team_id (str): Team ID.
        code_user_id (str): BindUser ID.
    """
    # 检查是否已经存在
    if (
        TeamMember.query.filter_by(
            team_id=team_id,
            code_user_id=code_user_id,
            status=0,
        ).first()
        is not None
    ):
        return

    new_team_member = TeamMember(
        id=ObjID.new_id(),
        team_id=team_id,
        code_user_id=code_user_id,
        im_user_id=None,
    )
    db.session.add(new_team_member)
    db.session.commit()


def create_team(app_info: dict, contact_id=None) -> Team:
    """Create a team.

    Args:
        name (str): Team name.
        app_info (dict): GitHub App info.

    Returns:
        Team: Team object.
    """

    current_user_id = session.get("user_id", None)
    if not current_user_id:
        abort(403, "can not found user by id")

    # 根据 Org ID 查找是否已经存在
    # 若存在，则返回当前的 team
    current_team = (
        db.session.query(Team)
        .filter(
            Team.platform_id == app_info["account"]["id"],
            Team.status == 0,
        )
        .first()
    )
    if current_team:
        if contact_id:
            db.session.query(TeamContact).filter(
                TeamContact.id == contact_id,
            ).update(dict(team_id=current_team.id))
        current_team.extra = app_info["account"]
        db.session.commit()
        return current_team

    new_team = Team(
        id=ObjID.new_id(),
        user_id=current_user_id,
        name=app_info["account"]["login"],
        description=None,
        platform_id=str(app_info["account"]["id"]),
        extra=app_info["account"],
    )

    db.session.add(new_team)
    db.session.flush()
    if contact_id:
        db.session.query(TeamContact).filter(
            TeamContact.id == contact_id,
        ).update(dict(team_id=new_team.id))

    # 创建 TeamMember
    current_bind_user = BindUser.query.filter(
        BindUser.user_id == current_user_id,
        BindUser.status == 0,
    ).first()
    if not current_bind_user:
        db.rollback()
        abort(403, "can not found bind user by id")

    new_team_member = TeamMember(
        id=ObjID.new_id(),
        team_id=new_team.id,
        code_user_id=current_bind_user.id,
        im_user_id=None,
    )

    db.session.add(new_team_member)
    db.session.commit()

    return new_team


def create_code_application(team_id: str, installation_id: str) -> CodeApplication:
    """Create a code application.

    Args:
        team_id (str): Team ID.
        installation_id (str): GitHub App installation ID.

    Returns:
        CodeApplication: CodeApplication object.
    """

    # 查询当前 team 是否已经存在 code application
    current_code_application = (
        db.session.query(CodeApplication)
        .filter(
            CodeApplication.team_id == team_id,
            CodeApplication.status.in_([0, 1]),
        )
        .first()
    )
    if current_code_application:
        # 更新 installation_id
        current_code_application.installation_id = installation_id
        db.session.commit()
        return current_code_application

    new_code_application = CodeApplication(
        id=ObjID.new_id(),
        team_id=team_id,
        installation_id=installation_id,
        platform="github",
    )

    db.session.add(new_code_application)
    db.session.commit()

    return new_code_application


def save_im_application(
    team_id, platform, app_id, app_secret, encrypt_key, verification_token
):
    if (
        db.session.query(IMApplication.id)
        .filter(
            IMApplication.team_id == team_id,
            IMApplication.status.in_([0, 1]),
        )
        .limit(1)
        .scalar()
    ):
        logging.warning("already bind im_application for team")
        # return abort(400, "already bind im_application for team")
    application = (
        db.session.query(IMApplication).filter(IMApplication.app_id == app_id).first()
    )
    if not application:
        application = IMApplication(
            id=ObjID.new_id(),
            platform=platform,
            team_id=team_id,
            app_id=app_id,
            app_secret=app_secret,
            extra=dict(encrypt_key=encrypt_key, verification_token=verification_token),
        )
        db.session.add(application)
        db.session.commit()
    else:
        db.session.query(IMApplication).filter(
            IMApplication.id == application.id,
        ).update(
            dict(
                platform=platform,
                team_id=team_id,
                app_id=app_id,
                app_secret=app_secret,
                extra=dict(
                    encrypt_key=encrypt_key, verification_token=verification_token
                ),
            )
        )
        db.session.commit()


def create_repo_chat_group_by_repo_id(user_id, team_id, repo_id, chat_name=None):
    team = get_team_by_id(team_id, user_id)
    repo = (
        db.session.query(Repo)
        .filter(
            Repo.id == repo_id,
            Repo.status == 0,
        )
        .first()
    )
    if not repo:
        return abort(404, "can not found repo by id")
    chat_group = (
        db.session.query(ChatGroup)
        .filter(
            ChatGroup.repo_id == repo.id,
            ChatGroup.status == 0,
        )
        .first()
    )
    if chat_group:
        return abort(400, "chat_group exists")

    app_id = (
        db.session.query(IMApplication.app_id)
        .filter(
            IMApplication.team_id == team.id,
            IMApplication.status.in_([0, 1]),
        )
        .limit(1)
        .scalar()
    )
    if not app_id:
        return abort(404, "im_application not exists")

    import tasks

    bot, application = tasks.get_bot_by_application_id(app_id)
    chat_group_url = f"{bot.host}/open-apis/im/v1/chats?uuid={repo.id}"
    owner_id = (
        db.session.query(IMUser.openid)
        .filter(
            IMUser.application_id == application.id,
            IMUser.user_id == user_id,
        )
        .limit(1)
        .scalar()
        or None
    )
    user_id_list = list(
        set(
            [
                openid
                for openid, in db.session.query(IMUser.openid)
                .join(
                    TeamMember,
                    TeamMember.im_user_id == IMUser.id,
                )
                .join(CodeUser, TeamMember.code_user_id == CodeUser.id)
                .join(
                    RepoUser,
                    RepoUser.bind_user_id == CodeUser.id,
                )
                .filter(
                    TeamMember.team_id == team.id,
                    RepoUser.repo_id == repo.id,
                )
            ]
        )
    )
    if len(user_id_list) == 0:
        return abort(404, "member list is empty")

    name = chat_name or f"{repo.name} 项目群"
    description = f"{repo.description or ''}"
    data = {
        "name": name,
        "description": description,
        "edit_permission": "all_members",  # TODO all_members/only_owner
        "set_bot_manager": True,  # 设置创建群的机器人为管理员
        "owner_id": owner_id if owner_id else user_id_list[0],
        "user_id_list": user_id_list,
    }
    result = bot.post(chat_group_url, json=data).json()
    chat_id = result.get("data", {}).get("chat_id")
    if not chat_id:
        logging.error("create chat_group error %r %r", data, result)
        return abort(400, "create chat group error")
    chat_group_id = ObjID.new_id()
    chat_group = ChatGroup(
        id=chat_group_id,
        repo_id=repo.id,
        im_application_id=application.id,
        chat_id=chat_id,
        name=name,
        description=description,
        extra=result,
    )
    db.session.add(chat_group)
    db.session.commit()
    # send card message, and pin repo card
    tasks.send_repo_to_chat_group.delay(repo.id, app_id, chat_id)
    return chat_id


def save_team_contact(user_id, first_name, last_name, email, role, newsletter):
    contact_id = ObjID.new_id()
    db.session.add(
        TeamContact(
            id=contact_id,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            newsletter=1 if newsletter else 0,
        )
    )
    db.session.commit()
    return contact_id


def get_code_users_by_openid(users):
    code_users = {
        openid: (code_user_id, code_user_name)
        for openid, code_user_id, code_user_name in db.session.query(
            IMUser.openid,
            CodeUser.user_id,
            CodeUser.name,
        )
        .join(
            TeamMember,
            TeamMember.code_user_id == CodeUser.id,
        )
        .join(
            IMUser,
            IMUser.id == TeamMember.im_user_id,
        )
        .filter(IMUser.openid.in_(users))
        .all()
    }
    return code_users


def get_assignees_by_openid(users):
    code_users = get_code_users_by_openid(users)
    assignees = [code_users[openid][1] for openid in users if openid in code_users]
    return assignees
