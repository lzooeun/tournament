import os
import django
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

# 1. Django 환경 설정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from tournament.models import Team, Match, Player
import discord
from discord.ext import commands
from discord import app_commands
from asgiref.sync import sync_to_async
import re
from django.db.models import Q

ADMIN_CHANNEL_ID = 1477441424764178604
TEAM_JOIN_CHANNEL_ID = 1477537891214426262
RESULT_SUBMIT_CHANNEL_ID = 1477537918817013760

app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

def run():
    # Koyeb은 기본적으로 8080 포트를 체크함
    app.run(host='0.0.0.0', port=8000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. 봇 기본 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 3. 봇이 켜졌을 때 슬래시 명령어 동기화!
@bot.event
async def on_ready():
    # 디스코드 서버에 우리가 만든 슬래시 명령어들을 등록하는 작업이야
    await bot.tree.sync() 
    print(f'✅ 봇 로그인 성공: {bot.user.name}')
    print('✅ 슬래시 명령어 동기화 완료!')

class ApprovalView(discord.ui.View):
    def __init__(self, match_id, match_num, image_url, winner_team, duration, original_channel_id, submitter_id):
        super().__init__(timeout=None)
        self.match_id = match_id
        self.match_num = match_num
        self.image_url = image_url
        self.winner_team = winner_team
        self.duration = duration
        self.original_channel_id = original_channel_id
        self.submitter_id = submitter_id

    @discord.ui.button(label="승인 (Approve)", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 🚨 1. 3초 타임아웃 킬러: 디스코드에게 "봇이 생각 중입니다..." 신호 보내기
        await interaction.response.defer(ephemeral=True)

        @sync_to_async
        def update_match():
            # 🚨 2. 잠자는 DB 깨우기 (무한 로딩 및 서버 에러 방지 마법의 코드)
            from django.db import close_old_connections
            close_old_connections()

            from tournament.models import Match, Team
            from tournament.views import get_standings 

            match = Match.objects.get(id=self.match_id)
            winner = Team.objects.filter(name=self.winner_team).first()
            
            system_messages = [] 

            if winner:
                # 1. 방금 이긴 팀의 세트 스코어 1점 추가!
                if winner == match.team_a:
                    match.team_a_score += 1
                else:
                    match.team_b_score += 1

                # 2. 다전제 룰에 따라 '시리즈가 최종 종료' 되었는지 확인
                is_series_finished = False
                if match.stage in ['GROUP', 'DEATHMATCH']:
                    is_series_finished = True 
                elif match.stage == 'SEMI':
                    if match.team_a_score >= 2 or match.team_b_score >= 2: # Bo3
                        is_series_finished = True
                elif match.stage == 'FINAL':
                    if match.team_a_score >= 3 or match.team_b_score >= 3: # Bo5
                        is_series_finished = True

                match.screenshot_url = self.image_url
                match.game_duration = self.duration

                # 3. [ 시리즈 완전 종료 시 ]
                if is_series_finished:
                    match.winner = winner
                    match.status = 'COMPLETED'
                    match.is_completed = True
                    
                    winner.wins += 1
                    winner.save()
                    loser = match.team_b if match.team_a == winner else match.team_a
                    loser.losses += 1
                    loser.save()
                    match.save()

                    # ==========================================
                    # 🎯 [ AUTO-PROGRESSION ] 토너먼트 자동 진출
                    # ==========================================
                    if match.stage == 'GROUP':
                        uncompleted_groups = Match.objects.filter(stage='GROUP', is_completed=False).count()
                        if uncompleted_groups == 0:
                            if not Match.objects.filter(match_number=7).exists():
                                std_a = get_standings('A')
                                std_b = get_standings('B')
                                a1, a2, a3 = std_a[0]['team'], std_a[1]['team'], std_a[2]['team']
                                b1, b2, b3 = std_b[0]['team'], std_b[1]['team'], std_b[2]['team']

                                Match.objects.create(match_number=7, stage='DEATHMATCH', team_a=a2, team_b=b3, is_completed=False)
                                Match.objects.create(match_number=8, stage='DEATHMATCH', team_a=b2, team_b=a3, is_completed=False)
                                system_messages.append("🔥 **[ GROUP STAGE 종료 ]** 데스매치 대진이 자동 생성되었습니다!")
                                system_messages.append(f"⚔️ **[ Deathmatch 1 ]** {a2.name} (A조 2위) vs {b3.name} (B조 3위)")
                                system_messages.append(f"⚔️ **[ Deathmatch 2 ]** {b2.name} (B조 2위) vs {a3.name} (A조 3위)")

                    elif match.stage == 'DEATHMATCH':
                        if match.match_number == 7:
                            b1 = get_standings('B')[0]['team']
                            if not Match.objects.filter(match_number=9).exists():
                                Match.objects.create(match_number=9, stage='SEMI', team_a=b1, team_b=winner, is_completed=False)
                                system_messages.append(f"🌟 **[ SEMI-FINAL 1 대진 확정 ]** {b1.name} (B조 1위) vs {winner.name} (DM1 승자)")
                        elif match.match_number == 8:
                            a1 = get_standings('A')[0]['team']
                            if not Match.objects.filter(match_number=10).exists():
                                Match.objects.create(match_number=10, stage='SEMI', team_a=a1, team_b=winner, is_completed=False)
                                system_messages.append(f"🌟 **[ SEMI-FINAL 2 대진 확정 ]** {a1.name} (A조 1위) vs {winner.name} (DM2 승자)")

                    elif match.stage == 'SEMI':
                        uncompleted_semis = Match.objects.filter(stage='SEMI', is_completed=False).count()
                        if uncompleted_semis == 0:
                            if not Match.objects.filter(match_number=11).exists():
                                sf1_match = Match.objects.get(match_number=9)
                                sf2_match = Match.objects.get(match_number=10)
                                Match.objects.create(match_number=11, stage='FINAL', team_a=sf1_match.winner, team_b=sf2_match.winner, is_completed=False)
                                system_messages.append("🏆 **[ GRAND FINAL 대진 확정 ]** 결승전 매치업이 생성되었습니다!")

                # 4. [ 세트 종료 (진행 중) ]
                else:
                    match.save()
                    system_messages.append(f"🔄 **[ SET SCORE UPDATED ]** 현재 스코어: **{match.team_a.name} ({match.team_a_score})** vs **({match.team_b_score}) {match.team_b.name}**")

            return winner.name if winner else "알 수 없음", system_messages
            
        # 함수 실행
        winner_name, sys_msgs = await update_match()
        
        original_channel = bot.get_channel(self.original_channel_id)
        if original_channel:
            msg = f"📢 <@{self.submitter_id}>님이 제출하신 **매치 #{self.match_num}** 결과가 승인되었습니다! ({winner_name} 승리)"
            if sys_msgs:
                msg += "\n\n" + "\n".join(sys_msgs)
            await original_channel.send(msg)
        
        # 버튼 비활성화 UI 업데이트
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        
        # 🚨 defer()를 썼기 때문에 followup.send()로 완료 메시지 쏘기!
        await interaction.followup.send("✅ 승인 처리 및 다음 스테이지 갱신 완료!", ephemeral=True)
        self.stop()

    @discord.ui.button(label="거절 (Reject)", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 거절 버튼도 터지지 않게 defer 추가
        await interaction.response.defer(ephemeral=True)

        original_channel = bot.get_channel(self.original_channel_id)
        if original_channel:
            await original_channel.send(f"❌ <@{self.submitter_id}>님이 제출하신 **매치 #{self.match_num}** 결과가 관리자에 의해 거절되었습니다.")
        
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        await interaction.followup.send(
            f"❌ 매치 #{self.match_id} 결과가 관리자에 의해 **거절**되었습니다.\n"
            f"제출된 스크린샷과 승리팀(`{self.winner_team}`) 정보가 일치하는지 확인 후 다시 제출해 주세요.", 
            ephemeral=False
        )
        self.stop()

# ==========================================
# [ 이벤트 ] 유저가 서버에 입장했을 때 (자동 닉네임 변경)
# ==========================================
@bot.event
async def on_member_join(member):
    WELCOME_CHANNEL_ID = 1477547605276754025  # 웰컴 메시지를 띄울 채널
    NOTICE_CHANNEL_ID = 1477535707840118837   # #공지사항 채널 ID
    RULES_CHANNEL_ID = 1477537413654908969    # #대회-룰 채널 ID
    WEB_CHANNEL_ID = 1477537596598124566      # #웹사이트 채널 ID
    INTRO_CHANNEL_ID = 1478475815007031296    # #자기소개 채널 ID

    @sync_to_async
    def get_player_riot_id(discord_id):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player
        try:
            player = Player.objects.get(discord_user_id=str(discord_id))
            return player.riot_id
        except Player.DoesNotExist:
            return None

    # DB 조회는 딱 한 번만!
    riot_id = await get_player_riot_id(member.id)
    is_registered = bool(riot_id) # riot_id가 있으면 True(참가자), 없으면 False(관전자)

    # 1. 닉네임 변경 시도
    changed_nick = False
    if is_registered:
        new_nick = riot_id[:32]
        try:
            await member.edit(nick=new_nick)
            changed_nick = True
        except Exception as e:
            print(f"❌ 닉네임 변경 실패: {e}")

    # 2. 🚨 누락되었던 핵심! 역할(Role) 자동 부여 로직
    guild = member.guild
    role_name = "참가자" if is_registered else "관전자"
    role = discord.utils.get(guild.roles, name=role_name)
    
    if role:
        try:
            await member.add_roles(role)
            print(f"✅ {member.name} 님에게 '{role_name}' 자동 부여 완료")
        except Exception as e:
            print(f"❌ '{role_name}' 역할 부여 실패 (권한 부족 등): {e}")

    # 3. 웰컴 메시지 전송
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        embed = discord.Embed(
            title="🎉 신규 참가자 입장!",
            description=f"환영합니다, <@{member.id}>님! 2026 TÆKTUBE INVITATIONAL에 합류하셨습니다.",
            color=0x2ecc71 if is_registered else 0x95a5a6 # 참가자/관전자 색상 구분
        )
        
        if changed_nick:
            embed.description += f"\n*(시스템에 의해 별명이 `{new_nick}`으로 자동 변경되었습니다.)*"

        if is_registered:
            embed.add_field(
                name="[ ⚔️ 인증 완료: 참가자 ]",
                value="DB에 선수 등록이 확인되어 **[참가자]** 권한이 자동 부여되었습니다.\n",
                inline=False
            )
            embed.add_field(
                name="[ STEP 1 ] 필독 채널 숙지",
                value=(
                    f"원활한 대회 진행을 위해 아래 세 채널을 반드시 정독해 주세요.\n"
                    f"<#{NOTICE_CHANNEL_ID}> | <#{RULES_CHANNEL_ID}> | <#{WEB_CHANNEL_ID}>"
                ),
                inline=False
            )
            embed.add_field(
                name="[ STEP 2 ] 자기소개 작성",
                value=(
                    f"다른 참가자들에게 본인을 어필해 보세요!\n"
                    f"👉 <#{INTRO_CHANNEL_ID}> 채널로 이동하여 `/자기소개` 명령어를 입력해 주세요."
                ),
                inline=False
            )
        else:
            embed.add_field(
                name="[ 🍿 인증 완료: 관전자 ]",
                value="DB에 등록되지 않은 계정이므로 **[관전자]** 권한이 자동 부여되었습니다.\n선수 등록을 원하실 경우 주최자에게 별도로 문의해 주십시오.",
                inline=False
            )

        embed.set_footer(text="* 권한에 오류가 있다면 관리자를 호출해 주세요.")
        
        await welcome_channel.send(content=f"<@{member.id}>", embed=embed)


# ==========================================
# 팀 이름 자동완성 함수
# ==========================================
async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    @sync_to_async
    def get_teams():
        from django.db import close_old_connections
        close_old_connections()
        # 사용자가 타이핑하는 글자가 포함된 팀만 DB에서 가져옴
        return list(Team.objects.filter(name__icontains=current)[:25])
    
    teams = await get_teams()
    # 디스코드 UI에 띄워줄 선택지 리스트 반환
    return [app_commands.Choice(name=t.name, value=t.name) for t in teams]

@bot.tree.command(name="결과제출", description="경기 결과 스크린샷과 승리팀을 제출합니다. (매치 자동 검색)")
@app_commands.describe(
    winner_team="승리한 팀 이름 (목록에서 선택)", 
    duration="경기 총 시간 (예 32:15)",
    image="결과 화면 스크린샷 첨부"
    )
@app_commands.autocomplete(winner_team=team_autocomplete)
async def submit_result(interaction: discord.Interaction, winner_team: str, duration: str, image: discord.Attachment):
    if interaction.channel_id != RESULT_SUBMIT_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{RESULT_SUBMIT_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return
    
    # 1. 이미지 파일 형식 확인
    if not image.content_type.startswith('image/'):
        await interaction.response.send_message("❌ 이미지 파일만 첨부할 수 있습니다!", ephemeral=True)
        return

    # 2. DB에서 알맞은 매치 자동으로 찾아오기 (비동기 처리)
    @sync_to_async
    def get_pending_match(team_name):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Match, Team
        
        # 입력한 팀이 존재하는지 확인
        team = Team.objects.filter(name=team_name).first()
        if not team:
            return None, None, f"❌ '{team_name}' 팀을 찾을 수 없습니다. 오타가 없는지 확인해 주세요."
        
        # 해당 팀이 A팀이거나 B팀이면서, 아직 안 끝난 경기 중 가장 번호가 앞서는(또는 가장 오래된) 경기 1개 찾기
        match = Match.objects.filter(
            Q(is_completed=False) & (Q(team_a=team) | Q(team_b=team))
        ).order_by('match_number').first() # match_number 기준으로 정렬 (필요에 따라 변경 가능)
        
        if not match:
            return None, None, f"❌ **{team.name}** 팀의 진행 대기 중인 매치가 없습니다."
            
        # 매치 상대팀이 누군지도 같이 넘겨주면 확인하기 좋음
        opponent = match.team_b.name if match.team_a == team else match.team_a.name
        return match.id, match.match_number, opponent, None
    
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if not admin_channel:
        await interaction.response.send_message("❌ 관리자 채널 세팅 오류! 개발자에게 문의하세요.", ephemeral=True)
        return

    # 함수 실행해서 매치 정보 받아오기
    match_id, match_num, opponent_name, error_msg = await get_pending_match(winner_team)

    # 에러가 있다면 (팀 이름 오타 등) 사용자에게만 살짝 알려주고 종료
    if error_msg:
        await interaction.response.send_message(error_msg, ephemeral=True)
        return

    # 3. 관리자용 승인 Embed 생성
    embed = discord.Embed(
        title=f"🛑 자동 매칭: 매치 #{match_num} 결과 승인 요청",
        description=(
            f"**제출자:** {interaction.user.mention}\n"
            f"**매치 정보:** **{winner_team}** vs **{opponent_name}**\n"
            f"**주장하는 승리팀:** **{winner_team}**\n\n"
            f"**경기 시간:** **{duration}**\n\n"
            f"아래 스크린샷을 확인하고 승인/거절을 선택해 주세요."
        ),
        color=discord.Color.blue()
    )
    embed.set_image(url=image.url)

    # 4. 버튼 뷰 연결 및 메시지 전송
    view = ApprovalView(match_id, match_num, image.url, winner_team, duration, interaction.channel_id, interaction.user.id)
    await admin_channel.send(embed=embed, view=view)
    
    await interaction.response.send_message("📨 결과 영수증이 관리자에게 전송되었습니다. 승인을 기다려주세요!", ephemeral=True)

# ==========================================
# /결과취소 슬래시 명령어 (관리자 전용)
# ==========================================
@bot.tree.command(name="결과취소", description="[관리자 전용] 잘못 입력된 경기 결과를 다시 대기 상태로 되돌립니다.")
@app_commands.describe(match_number="취소할 경기 번호를 숫자로 입력하세요 (예: 1)")
@app_commands.default_permissions(administrator=True)
async def cancel_result_slash(interaction: discord.Interaction, match_number: int):
    
    @sync_to_async
    def rollback_match(m_num):
        from django.db import close_old_connections
        close_old_connections()
        try:
            # 1. DB에서 해당 번호의 경기 찾기
            match = Match.objects.get(match_number=m_num)
            
            # 2. 이미 대기 중인 경기라면 취소할 필요가 없음
            if match.status != 'COMPLETED' or not match.winner:
                return False, f"❌ Game {m_num}은(는) 아직 결과가 입력되지 않았습니다. (현재 상태: {match.get_status_display()})"
            
            winner = match.winner
            # 패배 팀 알아내기
            loser = match.team_b if match.team_a == winner else match.team_a
            
            # 3. 두 팀의 승패 기록을 원래대로(-1) 삭감! (데이터 롤백)
            if winner.wins > 0:
                winner.wins -= 1
                winner.save()
            if loser.losses > 0:
                loser.losses -= 1
                loser.save()
            
            # 4. 경기 상태를 다시 초기화
            match.status = 'PENDING'
            match.winner = None
            match.game_duration = None
            match.is_completed = False 
            match.screenshot_url = None
            match.save()
            
            return True, f"⏪ **Game {m_num} 결과 취소 완료!**\n{winner.name}의 1승과 {loser.name}의 1패가 삭감되었고, 경기가 다시 대기 중 상태로 돌아갔습니다."
            
        except Match.DoesNotExist:
            return False, f"❌ {m_num}번 경기를 DB에서 찾을 수 없습니다."
        except Exception as e:
            return False, f"❌ 오류 발생: {str(e)}"

    # 봇이 생각하는 동안 대기
    await interaction.response.defer()
    
    # 롤백 함수 실행
    success, result_msg = await rollback_match(match_number)
    
    # 디스코드 채널에 결과 전송
    await interaction.followup.send(result_msg)

# ==========================================
# /팀가입 슬래시 명령어 (탕치기 기능 + 빈 팀 자동 삭제)
# ==========================================
@bot.tree.command(name="팀가입", description="원하는 팀에 가입하거나 이동합니다.")
@app_commands.describe(team_name="가입할 팀을 선택하세요")
@app_commands.autocomplete(team_name=team_autocomplete)
async def join_team_slash(interaction: discord.Interaction, team_name: str):
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 기간이 마감되어 더 이상 팀을 이동할 수 없습니다.", ephemeral=True)
        return
    
    user_id = str(interaction.user.id)
    
    @sync_to_async
    def process_join_team(d_id, t_name):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player, Team
        try:
            player = Player.objects.get(discord_user_id=d_id)
            target_team = Team.objects.get(name=t_name)
            
            if target_team.players.count() >= 5 and player.team != target_team:
                return False, f"❌ **{target_team.name}** 팀은 이미 5명이 꽉 찼습니다! 다른 팀을 알아보세요."
            
            if player.team == target_team:
                return False, f"⚠️ 이미 **{target_team.name}** 팀에 소속되어 있습니다."
            
            old_team = player.team
            old_team_name = old_team.name if old_team else "무소속"
            
            # 1. 팀 변경 및 DB 저장
            player.team = target_team
            player.save()
            
            # 2. 🚨 [ 핵심 ] 기존에 있던 팀이 0명이 되었는지 확인하고 폭파!
            deleted_team_name = None
            if old_team and old_team.players.count() == 0:
                deleted_team_name = old_team.name
                old_team.delete()
            
            return True, (player.riot_id, old_team_name, target_team.name, deleted_team_name)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다. 주최자에게 디스코드 ID 등록을 요청하세요."
        except Team.DoesNotExist:
            return False, f"❌ '{t_name}' 팀을 찾을 수 없습니다."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    await interaction.response.defer()
    
    success, result = await process_join_team(user_id, team_name)
    
    if success:
        riot_id, old_team, new_team, deleted_team = result
        guild = interaction.guild
        member = interaction.user
        
        # ==========================================
        # 🚨 [추가 1] 새 팀 역할 부여 & 이전 팀 역할 회수
        # ==========================================
        # 1) 새 역할 부여
        new_role = discord.utils.get(guild.roles, name=new_team)
        if not new_role:
            new_role = await guild.create_role(name=new_team, mentionable=True, reason="임시 팀 가입")
        await member.add_roles(new_role)
        
        # 2) 이전 역할 회수
        if old_team != "무소속":
            old_role = discord.utils.get(guild.roles, name=old_team)
            if old_role:
                await member.remove_roles(old_role)

        # ==========================================
        # 🚨 [추가 2] 0명 남은 빈 팀의 통화방 & 역할 자동 폭파!
        # ==========================================
        if deleted_team:
            # 1) 채널 삭제
            channel_to_delete = discord.utils.get(guild.voice_channels, name=f"🔊-{deleted_team}")
            if channel_to_delete:
                try:
                    await channel_to_delete.delete()
                except Exception as e:
                    print(f"채널 삭제 오류: {e}")
            
            # 2) 역할 삭제
            role_to_delete = discord.utils.get(guild.roles, name=deleted_team)
            if role_to_delete:
                try:
                    await role_to_delete.delete()
                except Exception as e:
                    print(f"역할 삭제 오류: {e}")
        
        embed = discord.Embed(title="🤝 팀 이적 완료!", color=0x2ecc71)
        embed.description = f"**{riot_id}** 님이 팀을 이동했습니다."
        embed.add_field(name="이전 소속", value=old_team, inline=True)
        embed.add_field(name="➡️", value=" ", inline=True)
        embed.add_field(name="새로운 소속", value=f"{new_role.mention}", inline=True) # 멘션으로 표시
        
        if deleted_team:
            embed.add_field(
                name="💥 팀 해체 알림", 
                value=f"**{deleted_team}** 팀에 남은 멤버가 없어 시스템에 의해 자동 해체(삭제)되었습니다.\n*(임시 통화방 및 팀 역할도 삭제되었습니다)*", 
                inline=False
            )
            
        embed.set_footer(text="웹사이트의 Team List에 즉각 반영되었습니다.")
        
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(result, ephemeral=True)
        

# ==========================================
# /팀확정 슬래시 명령어 (시스템 드래프트 + 채널 자동 생성)
# ==========================================
TEAM_JOIN_LOCKED = False 

@bot.tree.command(name="팀확정", description="[관리자 전용] 이적 시장을 마감하고, 미완성 팀을 자동 완성 및 확정합니다.")
@app_commands.default_permissions(administrator=True)
async def confirm_teams_slash(interaction: discord.Interaction):
    global TEAM_JOIN_LOCKED
    
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ 이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    # 봇이 계산할 시간이 많이 필요하므로 대기 상태로 전환
    await interaction.response.defer()

    # ==========================================
    # 🚨 [ STEP 1 ] 시스템 강제 드래프트 (미완성 팀 조립)
    # ==========================================
    @sync_to_async
    def auto_draft_teams():
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Team, Player
        from django.db.models import Count
        import random

        draft_logs = []
        
        # 1. 현재 팀 현황 파악 (인원수 기준 내림차순 정렬: 4명 -> 3명 -> 2명 -> 1명)
        teams = list(Team.objects.annotate(p_count=Count('players')).order_by('-p_count'))
        incomplete_teams = [t for t in teams if t.p_count < 5]

        # 2. 2명 이하인 소수 팀 강제 해체 (듀오 찢기)
        teams_to_destroy = [t for t in incomplete_teams if t.p_count <= 2]
        for t in teams_to_destroy:
            for p in t.players.all():
                p.team = None
                p.save()
            draft_logs.append(f"💥 **{t.name}** 팀 (인원 부족으로 시스템 강제 해체 ➡️ 전원 FA 전환)")
            incomplete_teams.remove(t)
            t.delete()

        # 3. FA 풀 가져오기 및 셔플 (랜덤성 보장)
        fa_players = list(Player.objects.filter(team__isnull=True))
        random.shuffle(fa_players)

        # 4. 3~4명인 팀에 FA 강제 할당 (티어 기반)
        for team in incomplete_teams:
            current_players = list(team.players.all())
            current_tiers = [p.tier for p in current_players]
            
            while team.players.count() < 5 and fa_players:
                # 팀에 없는 티어 찾기 (1~5 중 없는 것)
                needed_tiers = [t for t in [1, 2, 3, 4, 5] if t not in current_tiers]
                
                assigned_player = None
                if needed_tiers:
                    # 필요한 티어와 일치하는 FA가 있는지 검색
                    for t in needed_tiers:
                        candidates = [p for p in fa_players if p.tier == t]
                        if candidates:
                            assigned_player = random.choice(candidates)
                            break
                
                # 일치하는 티어가 없으면 남은 FA 중 완전 무작위 배정
                if not assigned_player:
                    assigned_player = fa_players[0]

                # 팀 배정 실행
                assigned_player.team = team
                assigned_player.save()
                fa_players.remove(assigned_player)
                current_tiers.append(assigned_player.tier)
                
                draft_logs.append(f"🔄 **[시스템 배정]** `{assigned_player.riot_id}` (Tier {assigned_player.tier}) ➡️ **{team.name}** 강제 합류")

        # 5. 남은 FA들로 새로운 팀 생성 (5명씩)
        new_team_count = 1
        while len(fa_players) >= 5:
            new_team_name = f"FA 연합 {new_team_count}팀"
            new_team = Team.objects.create(name=new_team_name)
            draft_logs.append(f"✨ **[신규 팀 창단]** FA 잔류 인원으로 **{new_team_name}**이(가) 결성되었습니다.")
            
            for _ in range(5):
                p = fa_players.pop(0)
                p.team = new_team
                p.save()
                draft_logs.append(f"   └ 🔄 `{p.riot_id}` (Tier {p.tier}) 합류")
            new_team_count += 1

        return draft_logs

    # ==========================================
    # 🚨 [ STEP 2 ] 기존의 팀 확정 및 채널 생성 로직
    # ==========================================
    @sync_to_async
    def get_final_teams():
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Team
        teams = list(Team.objects.prefetch_related('players').all())
        return [(t.name, [p.discord_user_id for p in t.players.all()]) for t in teams]

    try:
        # 먼저 시스템 드래프트 돌리기
        draft_results = await auto_draft_teams()
        
        # 드래프트가 끝난 최종 팀 명단 가져오기
        teams_data = await get_final_teams()
        setup_logs = []

        for team_name, player_ids in teams_data:
            # 1. 역할 생성 및 부여
            role = discord.utils.get(guild.roles, name=team_name)
            if not role:
                role = await guild.create_role(name=team_name, hoist=True, mentionable=True, reason="팀 확정")
            
            assigned_count = 0
            for d_id in player_ids:
                member = guild.get_member(int(d_id))
                if not member:
                    try:
                        member = await guild.fetch_member(int(d_id))
                    except discord.NotFound:
                        continue 
                
                if member and role not in member.roles:
                    await member.add_roles(role)
                    assigned_count += 1
            setup_logs.append(f"📁 `{team_name}` 채널 및 역할 세팅 완료 ({len(player_ids)}명)")

            # 2. 카테고리 및 채널 생성 (기존과 동일하게 권한 빡세게!)
            category_name = f"[ {team_name} ]"
            category = discord.utils.get(guild.categories, name=category_name)
            
            txt_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            vc_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
                role: discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True, 
                    move_members=True, manage_channels=True
                )
            }
            fan_overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }

            if not category:
                category = await guild.create_category(name=category_name)
                await guild.create_text_channel(name="🔒전략-회의", category=category, overwrites=txt_overwrites)
                await guild.create_text_channel(name="💬참가-요청", category=category, overwrites=fan_overwrites)
                await guild.create_voice_channel(name="🔊-보이스", category=category, overwrites=vc_overwrites)

        # 3. 이적 시장 잠금!
        TEAM_JOIN_LOCKED = True

        # 4. 화려한 결과 임베드 출력
        embed = discord.Embed(
            title="🔒 [ 이적 시장 종료 & 최종 로스터 확정 ]", 
            description="**이적 시장이 완전히 마감되었으며, 미완성 팀에 대한 시스템 강제 재배치가 완료되었습니다.**\n더 이상 `/팀가입`, `/팀생성`을 사용할 수 없습니다.",
            color=0xE74C3C
        )
        
        # 드래프트 로그가 있으면 임베드에 추가해서 보여주기!
        if draft_results:
            draft_text = "\n".join(draft_results)
            # 글자가 너무 길면 잘릴 수 있으므로 나눠서 처리
            if len(draft_text) > 1024:
                draft_text = draft_text[:1000] + "\n... (이하 생략)"
            embed.add_field(name="🤖 [ 시스템 강제 재배치 결과 (System Draft) ]", value=draft_text, inline=False)
            
        setup_text = "\n".join(setup_logs)
        embed.add_field(name="✅ [ 채널 세팅 현황 ]", value=setup_text, inline=False)
        embed.set_footer(text="* 시스템의 결정은 절대적이며, 번복되지 않습니다.")
        
        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.followup.send("❌ 봇 권한이 부족합니다! 서버 설정에서 역할을 위로 올려주세요.")
    except Exception as e:
        await interaction.followup.send(f"❌ 오류 발생: {str(e)}")

# ==========================================
# [ UI View ] 보이스 채널 관전 승인/거절 버튼
# ==========================================
class SpectateApprovalView(discord.ui.View):
    def __init__(self, requester: discord.Member, team_role: discord.Role, voice_channel: discord.VoiceChannel):
        super().__init__(timeout=None) # 시간제한 없음
        self.requester = requester
        self.team_role = team_role
        self.voice_channel = voice_channel

    @discord.ui.button(label="✅ 관전 승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 버튼 누른 사람이 해당 팀 소속인지 확인
        if self.team_role not in interaction.user.roles:
            await interaction.response.send_message("❌ 소속 팀원만 승인할 수 있습니다.", ephemeral=True)
            return
        
        # 👑 요청자에게 해당 보이스 채널 '접속(O), 말하기(X)' 권한 부여!
        await self.voice_channel.set_permissions(self.requester, connect=True, speak=False)
        
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"🎉 <@{self.requester.id}> 님의 관전이 승인되었습니다! 보이스 채널에 접속하세요.")

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.team_role not in interaction.user.roles:
            await interaction.response.send_message("❌ 소속 팀원만 거절할 수 있습니다.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"🚫 <@{self.requester.id}> 님의 관전 요청이 거절되었습니다.")

# ==========================================
# /관전요청 슬래시 명령어 (팬 소통방 전용)
# ==========================================
@bot.tree.command(name="관전요청", description="[관전자/타팀 전용] 현재 채널의 팀 보이스 방에 입장(듣기 전용)을 요청합니다.")
async def spectate_request_slash(interaction: discord.Interaction):
    category = interaction.channel.category
    
    # 해당 채널이 "[ 팀이름 ]" 형식의 카테고리 안에 있는지 검증
    if not category or not category.name.startswith("[ ") or not category.name.endswith(" ]"):
        await interaction.response.send_message("❌ 이 명령어는 각 팀의 `#💬참가-요청` 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    # 카테고리 이름 "[ Team A ]"에서 "Team A"만 쏙 빼내기
    team_name = category.name.strip("[] ")
    guild = interaction.guild
    team_role = discord.utils.get(guild.roles, name=team_name)
    voice_channel = discord.utils.get(category.voice_channels, name="🔊-보이스")
    
    if not team_role or not voice_channel:
        await interaction.response.send_message("❌ 팀 정보나 보이스 채널을 찾을 수 없습니다.", ephemeral=True)
        return

    # 이미 같은 팀 소속이면 컷
    if team_role in interaction.user.roles:
        await interaction.response.send_message("⚠️ 본인 소속 팀의 보이스 채널은 요청 없이 자유롭게 들어갈 수 있습니다.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎫 보이스 채널 관전 요청",
        description=f"<@{interaction.user.id}> 님이 **{team_name}** 팀의 보이스 채널에 입장을 요청했습니다.\n(승인 시 마이크가 차단된 듣기 전용으로 접속됩니다.)",
        color=0x3498DB
    )
    
    view = SpectateApprovalView(interaction.user, team_role, voice_channel)
    
    # 팀원들을 멘션하면서 버튼 띄워주기
    await interaction.response.send_message(content=f"{team_role.mention} 관전 요청이 들어왔습니다!", embed=embed, view=view)

# ==========================================
# /자기소개 슬래시 명령어 (모든 유저 사용 가능)
# ==========================================
@bot.tree.command(name="자기소개", description="[참가자 전용] 지정된 채널에서 자기소개를 작성합니다.")
@app_commands.describe(
    riot_id="롤 닉네임 (예: Hide on bush#KR1)",
    positions="주로 가는 라인 (복수 선택 가능, 예: 미드/원딜/서폿)",
    current_tier="현재 솔랭 티어 (예: 플래티넘 3)",
    highest_tier="역대 최고 티어 (예: 에메랄드 1)",
    appeal="어필 한마디 (예: 국밥 탑라이너입니다. 잘 부탁드립니다!)"
)
async def self_introduction(
    interaction: discord.Interaction, 
    riot_id: str, 
    positions: str, 
    current_tier: str, 
    highest_tier: str, 
    appeal: str
):
    # 🚨 자기소개 채널 ID를 여기에 입력하세요! (다른 채널에서 쓰면 봇이 막음)
    INTRO_CHANNEL_ID = 1478475815007031296  # 예: #자기소개 채널 ID
    
    if interaction.channel_id != INTRO_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ 이 명령어는 <#{INTRO_CHANNEL_ID}> 채널에서만 사용할 수 있습니다!", 
            ephemeral=True
        )
        return

    # 자기소개 임베드 생성
    embed = discord.Embed(
        title="✨ NEW CHALLENGER APPEARED!",
        description=f"<@{interaction.user.id}>님의 자기소개입니다.",
        color=0x6C85DE
    )
    
    # 디스코드 프로필 사진을 썸네일로 사용
    if interaction.user.display_avatar:
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
    embed.add_field(name="[롤 닉네임]", value=f"**{riot_id}**", inline=False)
    embed.add_field(name="[선호 포지션]", value=f"`{positions}`", inline=False)
    embed.add_field(name="[현재 티어]", value=current_tier, inline=True)
    embed.add_field(name="[최고 티어]", value=highest_tier, inline=True)
    embed.add_field(name="[어필 한마디]", value=f"> {appeal}", inline=False)
    
    embed.set_footer(text="2026 TÆKTUBE INVITATIONAL")

    await interaction.response.send_message(embed=embed)

# ==========================================
# /팀생성 슬래시 명령어
# ==========================================
@bot.tree.command(name="팀생성", description="새로운 팀을 창단합니다. (기존 팀에 소속되어 있다면 자동으로 탈퇴됩니다.)")
@app_commands.describe(team_name="생성할 팀의 이름을 입력하세요")
async def create_team_slash(interaction: discord.Interaction, team_name: str):
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 시장이 종료되어 더 이상 팀을 생성할 수 없습니다.", ephemeral=True)
        return

    @sync_to_async
    def process_create_team(d_id, t_name):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player, Team
        try:
            player = Player.objects.get(discord_user_id=d_id)
            
            # 1. 중복 이름 검사
            if Team.objects.filter(name__iexact=t_name).exists():
                return False, f"❌ **{t_name}** (이)라는 이름의 팀이 이미 존재합니다. 다른 이름을 골라주세요."
            
            old_team_name = None
            deleted_team_name = None
            
            # ==========================================
            # 🚨 [추가된 로직] 이미 팀이 있다면 자동 탈퇴 처리
            # ==========================================
            if player.team:
                old_team = player.team
                old_team_name = old_team.name
                
                # 플레이어를 이전 팀에서 뺌
                player.team = None
                player.save()
                
                # 만약 내가 나갔는데 이전 팀에 남은 멤버가 0명이라면? -> 폭파 예약
                if old_team.players.count() == 0:
                    deleted_team_name = old_team.name
                    old_team.delete()
            
            # 2. 새 팀 생성 (본인이 방장 기록됨)
            new_team = Team.objects.create(name=t_name, leader_discord_id=d_id)
            player.team = new_team
            player.save()
            
            return True, (player.riot_id, new_team.name, old_team_name, deleted_team_name)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다. 참가 신청을 먼저 해주세요."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    await interaction.response.defer()

    success, result = await process_create_team(str(interaction.user.id), team_name)

    if success:
        riot_id, new_team_name, old_team_name, deleted_team_name = result
        guild = interaction.guild
        member = interaction.user
        
        # ==========================================
        # 🚨 [1] 이전 팀 역할 회수 및 빈 팀 폭파 처리
        # ==========================================
        if old_team_name:
            old_role = discord.utils.get(guild.roles, name=old_team_name)
            if old_role:
                try:
                    await member.remove_roles(old_role)
                except Exception as e:
                    print(f"역할 회수 오류: {e}")
                    
        if deleted_team_name:
            channel_to_delete = discord.utils.get(guild.voice_channels, name=f"🔊-{deleted_team_name}")
            if channel_to_delete:
                try:
                    await channel_to_delete.delete()
                except Exception as e:
                    print(f"이전 채널 삭제 오류: {e}")
            
            role_to_delete = discord.utils.get(guild.roles, name=deleted_team_name)
            if role_to_delete:
                try:
                    await role_to_delete.delete()
                except Exception as e:
                    print(f"이전 역할 삭제 오류: {e}")

        # ==========================================
        # 🚨 [2] 새 팀 역할 생성 및 부여
        # ==========================================
        new_role = discord.utils.get(guild.roles, name=new_team_name)
        if not new_role:
            new_role = await guild.create_role(name=new_team_name, mentionable=True, reason="임시 팀 창단")
        await member.add_roles(new_role)

        # ==========================================
        # 🚨 [3] 임시 스크림 보이스 채널 생성 (강력한 방장 권한 세팅)
        # ==========================================
        category_name = "🔄 임시 스크림 룸"
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)
            
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
            new_role: discord.PermissionOverwrite(
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True
            )
        }
            
        try:
            await guild.create_voice_channel(name=f"🔊-{new_team_name}", category=category, overwrites=overwrites)
        except Exception as e:
            print(f"새 채널 생성 오류: {e}")
            
        # ==========================================
        # 🚨 [4] 성공 메시지 전송 (탈퇴 알림 포함)
        # ==========================================
        embed = discord.Embed(title="🎊 신규 팀 창단 완료!", color=0xF1C40F)
        embed.description = f"**{riot_id}** 님이 새로운 팀을 창단했습니다!"
        
        # 이전 팀이 있었다면 표시해줌
        if old_team_name:
            embed.add_field(name="[ 이전 소속 ]", value=f"~~{old_team_name}~~ (탈퇴)", inline=True)
            embed.add_field(name="➡️", value=" ", inline=True)
            
        embed.add_field(name="[ 신규 팀 이름 ]", value=f"{new_role.mention}", inline=True)
        
        # 이전 팀이 터졌다면 알려줌
        if deleted_team_name:
            embed.add_field(
                name="💥 구 팀 해체 알림", 
                value=f"기존에 속해있던 **{deleted_team_name}** 팀에 남은 멤버가 없어 시스템에 의해 자동 해체(삭제)되었습니다.", 
                inline=False
            )
            
        embed.add_field(
            name="[ 안내 ]", 
            value=f"이제 다른 참가자들이 `/팀가입`을 통해 합류할 수 있습니다.\n**임시 통화방(`🔊-{new_team_name}`)**과 👑 **채널 관리 권한**이 부여되었습니다!", 
            inline=False
        )
        embed.set_footer(text="팀장님, 멋진 로스터를 꾸려 우승을 차지해 보세요!")
        
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(result, ephemeral=True)

# ==========================================
# /팀명변경 슬래시 명령어 (이적 시장 한정, 누구나 변경 가능)
# ==========================================
@bot.tree.command(name="팀명변경", description="소속된 팀의 이름을 변경합니다. (이적 시장 기간 한정)")
@app_commands.describe(new_team_name="새로운 팀 이름을 입력하세요 (최대 30자)")
async def rename_team_slash(interaction: discord.Interaction, new_team_name: str):
    # 1. 지정된 채널인지 확인
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    # 2. 이적 시장 마감 여부 확인
    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 시장 및 로스터가 확정되어 더 이상 팀 이름을 변경할 수 없습니다.", ephemeral=True)
        return

    user_id = str(interaction.user.id)

    # 3. DB 로직 처리 (비동기)
    @sync_to_async
    def process_rename_team(d_id, new_name):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player, Team
        try:
            if len(new_name) > 50:
                return False, "❌ 팀 이름은 최대 50자까지만 설정할 수 있습니다."

            player = Player.objects.get(discord_user_id=d_id)
            
            if not player.team:
                return False, "❌ 소속된 팀이 없습니다. 먼저 팀을 생성하거나 가입해주세요."
                
            team = player.team
            old_name = team.name

            # 기존 이름과 똑같이 입력한 경우
            if old_name == new_name:
                return False, "⚠️ 기존과 동일한 이름입니다."

            # 중복 이름 검사 (대소문자 무시하고 겹치는지 확인)
            if Team.objects.filter(name__iexact=new_name).exists():
                return False, f"❌ **{new_name}** (이)라는 이름의 팀이 이미 존재합니다. 다른 이름을 골라주세요."

            # 검문 통과! DB에 새 이름 저장
            team.name = new_name
            team.save()

            return True, (old_name, new_name, player.riot_id)

        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    # 봇이 3초 안에 응답 못해서 터지는 거 방지!
    await interaction.response.defer()

    success, result = await process_rename_team(user_id, new_team_name)

    if success:
        old_name, new_name, riot_id = result
        guild = interaction.guild

        # ==========================================
        # 🚨 [ 디스코드 연동 ] 역할(Role) & 통화방 이름 즉시 변경
        # ==========================================
        # 1) 기존 역할 이름 변경
        role = discord.utils.get(guild.roles, name=old_name)
        if role:
            try:
                await role.edit(name=new_name)
            except Exception as e:
                print(f"역할 이름 변경 오류: {e}")

        # 2) 기존 보이스 채널 이름 변경
        voice_channel = discord.utils.get(guild.voice_channels, name=f"🔊-{old_name}")
        if voice_channel:
            try:
                await voice_channel.edit(name=f"🔊-{new_name}")
            except Exception as e:
                print(f"통화방 이름 변경 오류: {e}")

        # 성공 메시지 전송
        embed = discord.Embed(title="🏷️ 팀 이름 변경 완료!", color=0x3498DB)
        embed.description = f"**{riot_id}** 님의 요청으로 팀 이름이 성공적으로 변경되었습니다."
        embed.add_field(name="[ 기존 이름 ]", value=f"~~{old_name}~~", inline=True)
        embed.add_field(name="➡️", value=" ", inline=True)
        embed.add_field(name="[ 새로운 이름 ]", value=f"{role.mention if role else f'**{new_name}**'}", inline=True)
        
        embed.set_footer(text="웹사이트와 소속 팀원들의 역할, 통화방 이름에 즉시 반영되었습니다.")
        
        await interaction.followup.send(embed=embed)
    else:
        # 실패 시 에러 메시지 전송 (본인에게만 보임)
        await interaction.followup.send(result, ephemeral=True)

# ==========================================
# /팀원추방 슬래시 명령어 (방출 + 빈 팀 자동 삭제)
# ==========================================
@bot.tree.command(name="팀원추방", description="같은 팀에 속한 멤버를 방출합니다. (이적 시장 기간 한정)")
@app_commands.describe(target_user="방출할 팀원을 선택하세요 (@멘션 또는 유저 선택)")
async def kick_teammate_slash(interaction: discord.Interaction, target_user: discord.Member):
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 시장이 종료되어 더 이상 팀원을 방출할 수 없습니다.", ephemeral=True)
        return

    caller_id = str(interaction.user.id)
    target_id = str(target_user.id)

    @sync_to_async
    def process_kick(c_id, t_id):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player
        try:
            caller = Player.objects.get(discord_user_id=c_id)
            target = Player.objects.get(discord_user_id=t_id)
            
            if not caller.team:
                return False, "❌ 본인이 소속된 팀이 없어 이 명령어를 사용할 수 없습니다."
            
            if c_id == t_id:
                return False, "❌ 자기 자신을 방출할 수 없습니다. 다른 팀으로 가려면 `/팀가입`을 이용하세요."
            
            if caller.team != target.team:
                return False, f"❌ <@{t_id}> 님은 **{caller.team.name}** 팀 소속이 아닙니다!"
            
            team = caller.team
            team_name = team.name
            target_riot_id = target.riot_id
            
            # 1. 방출 실행
            target.team = None
            target.save()
            
            # 2. 🚨 [ 핵심 ] 방출하고 나서 팀이 0명이 되었는지 확인하고 폭파!
            deleted_team_name = None
            if team.players.count() == 0:
                deleted_team_name = team.name
                team.delete()
            
            return True, (target_riot_id, team_name, deleted_team_name)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록되지 않은 참가자가 포함되어 있습니다."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    await interaction.response.defer()
    
    success, result = await process_kick(caller_id, target_id)
    
    if success:
        target_riot_id, team_name, deleted_team = result
        guild = interaction.guild
        
        # ==========================================
        # 🚨 [추가 1] 방출된 유저의 팀 역할 회수
        # ==========================================
        role_to_remove = discord.utils.get(guild.roles, name=team_name)
        if role_to_remove:
            try:
                await target_user.remove_roles(role_to_remove)
            except Exception as e:
                print(f"역할 회수 오류: {e}")

        # ==========================================
        # 🚨 [추가 2] 0명 남은 빈 팀의 통화방 & 역할 폭파
        # ==========================================
        if deleted_team:
            channel_to_delete = discord.utils.get(guild.voice_channels, name=f"🔊-{deleted_team}")
            if channel_to_delete:
                try:
                    await channel_to_delete.delete()
                except Exception as e:
                    print(f"채널 삭제 오류: {e}")
                    
            role_to_delete = discord.utils.get(guild.roles, name=deleted_team)
            if role_to_delete:
                try:
                    await role_to_delete.delete()
                except Exception as e:
                    print(f"역할 삭제 오류: {e}")
        
        embed = discord.Embed(title="🚨 팀원 방출 (FA 전환)", color=0xE74C3C)
        embed.description = f"**{target_riot_id}** 님이 **{team_name}** 팀에서 방출되었습니다."
        
        if deleted_team:
            embed.add_field(
                name="💥 팀 해체 알림", 
                value=f"해당 방출로 인해 **{deleted_team}** 팀의 인원이 0명이 되어 자동 해체(삭제)되었습니다.\n*(임시 통화방 및 팀 역할도 삭제되었습니다)*", 
                inline=False
            )
            
        embed.set_footer(text="방출된 선수는 다시 무소속 신분이 되며 웹사이트 명단에서 제외됩니다.")
        
        await interaction.followup.send(content=f"<@{target_id}>", embed=embed)
    else:
        await interaction.followup.send(result, ephemeral=True)
        
# ==========================================
# /대진표생성 슬래시 명령어 (관리자 전용) - 스케줄링 포함
# ==========================================
@bot.tree.command(name="대진표생성", description="[관리자 전용] 6팀 조별 리그 추첨 및 대진표를 생성합니다. (시간 자동 배정)")
@app_commands.describe(start_hour="대회 시작 시간 (예: 밤 10시 시작이면 22 입력, 기본값 22)")
@app_commands.default_permissions(administrator=True)
async def generate_bracket_slash(interaction: discord.Interaction, start_hour: int = 22):
    # DB 작업 대기
    await interaction.response.defer()

    @sync_to_async
    def create_matches(start_h):
        # 🚨 끊어진 DB 연결 초기화 (무한 로딩 방지용 마법의 한 줄)
        from django.db import close_old_connections
        close_old_connections()
        
        from tournament.models import Team, Match
        import random

        # 1. 팀 검증 및 중복 생성 방지
        teams = list(Team.objects.all())
        if len(teams) != 6:
            return False, f"시스템 오류: 현재 등록된 팀이 {len(teams)}개입니다. 6개 팀이 확정되어야 합니다."
        if Match.objects.exists():
            return False, "시스템 오류: 이미 생성된 대진표가 존재합니다. DB를 초기화해 주세요."

        # 2. 랜덤 셔플 및 조 편성
        random.shuffle(teams)
        group_a = teams[:3]
        group_b = teams[3:]

        # 조 저장
        for t in group_a:
            t.group = 'A'
            t.save()
        for t in group_b:
            t.group = 'B'
            t.save()

        # 3. 각 조별 3경기 대진표 (블루/레드 밸런스 완벽 보장)
        a_matches = [
            (group_a[0], group_a[1]), # Round 1
            (group_a[1], group_a[2]), # Round 2
            (group_a[2], group_a[0]), # Round 3
        ]
        b_matches = [
            (group_b[0], group_b[1]),
            (group_b[1], group_b[2]),
            (group_b[2], group_b[0]),
        ]

        created_matches = []
        match_number = 1

        # 4. 시간 배정 및 DB 저장 로직 (교차 편성)
        for round_idx in range(3):
            # 1시간 단위로 시간 계산 (예: 22:00, 23:00, 24:00(00:00))
            current_h = (start_h + round_idx) % 24
            time_str = f"{current_h:02d}:00"

            # [ Group A 경기 생성 ]
            blue_a, red_a = a_matches[round_idx]
            Match.objects.create(
                match_number=match_number,
                stage='GROUP',
                team_a=blue_a,
                team_b=red_a,
                scheduled_time=time_str,
                is_completed=False
            )
            created_matches.append({
                'num': match_number, 'group': 'A', 'blue': blue_a.name, 'red': red_a.name, 'time': time_str
            })
            match_number += 1

            # [ Group B 경기 생성 ] - Group A와 동일한 시간 배정
            blue_b, red_b = b_matches[round_idx]
            Match.objects.create(
                match_number=match_number,
                stage='GROUP',
                team_a=blue_b,
                team_b=red_b,
                scheduled_time=time_str,
                is_completed=False
            )
            created_matches.append({
                'num': match_number, 'group': 'B', 'blue': blue_b.name, 'red': red_b.name, 'time': time_str
            })
            match_number += 1

        return True, (group_a, group_b, created_matches)

    # 함수 실행
    success, result = await create_matches(start_hour)
    if not success:
        await interaction.followup.send(f"[ ERROR ]\n{result}")
        return

    # 5. 디스코드 임베드 출력
    group_a, group_b, match_list = result
    
    embed = discord.Embed(
        title="[ SYSTEM: GROUP STAGE BRACKET ]",
        description=f"6팀 조 추첨 및 조별 리그 매치업이 생성되었습니다.\n**시작 기준 시간:** `{start_hour:02d}:00`",
        color=0x111111
    )
    
    a_names = " / ".join([t.name for t in group_a])
    b_names = " / ".join([t.name for t in group_b])
    embed.add_field(name="[ GROUP A ]", value=f"**{a_names}**", inline=False)
    embed.add_field(name="[ GROUP B ]", value=f"**{b_names}**", inline=False)
    embed.add_field(name="+--------------------------------------+", value="\u200b", inline=False)

    # 출력 (2경기씩 묶어서)
    for i in range(0, 6, 2):
        m1 = match_list[i]
        m2 = match_list[i+1]
        
        # ⏰ 임베드에도 배정된 시간이 표시되도록 수정!
        val = (
            f"⏰ **{m1['time']}** | Game {m1['num']:02d} [ Group A ] : {m1['blue']} (B) vs {m1['red']} (R)\n"
            f"⏰ **{m2['time']}** | Game {m2['num']:02d} [ Group B ] : {m2['blue']} (B) vs {m2['red']} (R)"
        )
        embed.add_field(name=f"[ ROUND {(i//2)+1} ]", value=val, inline=False)

    embed.set_footer(text="* 웹사이트 Match Hub에 즉시 스케줄이 반영되었습니다.")
    
    await interaction.followup.send(embed=embed)

# ==========================================
# /경기알림 슬래시 명령어 (관리자 전용)
# ==========================================
@bot.tree.command(name="경기알림", description="[관리자 전용] 특정 매치에 참여하는 양 팀의 비밀 채널에 경기 준비 알림(Ping)을 보냅니다.")
@app_commands.describe(match_num="알림을 보낼 매치 번호 (예: 1)")
@app_commands.default_permissions(administrator=True)
async def match_notification_slash(interaction: discord.Interaction, match_num: int):
    # 디스코드 봇이 응답을 생각하는 시간을 벌어줌 (데이터베이스 조회 시 필수)
    await interaction.response.defer(ephemeral=True)

    # 1. DB에서 해당 번호의 매치 정보 가져오기
    @sync_to_async
    def get_match_teams(m_num):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Match
        
        match = Match.objects.filter(match_number=m_num).first()
        if not match:
            return None, f"❌ Game {m_num} 매치를 찾을 수 없습니다."
        if match.is_completed:
            return None, f"❌ Game {m_num} 매치는 이미 종료되었습니다."
        if not match.team_a or not match.team_b:
            return None, f"❌ Game {m_num} 매치에 아직 팀이 모두 배정되지 않았습니다."
        
        return (match.team_a.name, match.team_b.name), None

    teams, error_msg = await get_match_teams(match_num)
    
    if error_msg:
        await interaction.followup.send(error_msg)
        return
        
    team_a_name, team_b_name = teams
    guild = interaction.guild
    notified_teams = []
    failed_teams = []

    # 2. 양 팀 채널에 보낼 🚨 경고용 브루탈리스트 임베드 디자인
    embed = discord.Embed(
        title="[ SYSTEM NOTIFICATION ]",
        description=f"**GAME {match_num}** 시작이 임박했습니다.\n\n해당 매치에 참여하는 로스터 전원은 즉시 **인게임 로비** 및 본 디스코드 **음성 채널**로 이동하여 대기하십시오.",
        color=0xE74C3C # 경고/긴급 느낌을 주는 시크한 레드
    )
    embed.add_field(name="[ MATCHUP ]", value=f"**{team_a_name}** vs **{team_b_name}**", inline=False)
    embed.add_field(name="[ PENALTY WARNING ]", value="지각 시 5분 단위로 밴 카드가 압수되며, 15분 경과 시 실격(Auto DQ) 처리됩니다.", inline=False)
    embed.set_footer(text="* Punctuality is strictly enforced.")

    # 3. 각 팀의 채널을 찾아서 메시지 쏘기
    for team_name in (team_a_name, team_b_name):
        # 팀 역할(Role) 찾기 (멘션용)
        role = discord.utils.get(guild.roles, name=team_name)
        
        # 팀 카테고리 찾기 (예: "[ Team A ]")
        category_name = f"[ {team_name} ]"
        category = discord.utils.get(guild.categories, name=category_name)
        
        # 카테고리 안의 텍스트 채널(전략-회의) 찾기
        target_channel = None
        if category:
            for channel in category.text_channels:
                if "전략-회의" in channel.name:
                    target_channel = channel
                    break
        
        # 채널과 역할이 모두 존재하면 멘션과 함께 알림 쏘기
        if target_channel and role:
            try:
                # 🔔 역할 멘션(@Team A)을 포함해서 전송!
                await target_channel.send(content=f"🔔 {role.mention}", embed=embed)
                notified_teams.append(team_name)
            except Exception:
                failed_teams.append(team_name)
        else:
            failed_teams.append(team_name)

    # 4. 명령어를 입력한 관리자에게 결과 보고
    result_msg = f"✅ **GAME {match_num}** 알림 전송 결과:\n"
    if notified_teams:
        result_msg += f"- 🟢 전송 성공: **{', '.join(notified_teams)}** 비밀 채널\n"
    if failed_teams:
        result_msg += f"- 🔴 전송 실패: **{', '.join(failed_teams)}** (채널이나 역할을 찾을 수 없음)"
        
    await interaction.followup.send(result_msg)

# ==========================================
# /스크림방복구 슬래시 명령어 (관리자 전용 - 1회성 동기화)
# ==========================================
@bot.tree.command(name="스크림방복구", description="[관리자 전용] 통화방/역할 생성 및 팀원에게 '킥 권한'을 일괄 부여합니다.")
@app_commands.default_permissions(administrator=True)
async def restore_voice_channels(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    category_name = "🔄 임시 스크림 룸"
    category = discord.utils.get(guild.categories, name=category_name)
    
    if not category:
        category = await guild.create_category(category_name)

    @sync_to_async
    def get_teams_and_players():
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Team
        
        teams_data = []
        for team in Team.objects.prefetch_related('players').all():
            player_ids = [player.discord_user_id for player in team.players.all()]
            teams_data.append((team.name, player_ids))
        return teams_data

    teams_data = await get_teams_and_players()
    created_channels = []
    created_roles = []
    updated_perms = []
    assigned_count = 0

    try:
        for team_name, player_ids in teams_data:
            # 1. 🏷️ 역할(Role)부터 복구 (채널 권한 설정에 써야 하므로 무조건 먼저!)
            role = discord.utils.get(guild.roles, name=team_name)
            if not role:
                role = await guild.create_role(name=team_name, mentionable=True, reason="스크림방 복구 및 역할 동기화")
                created_roles.append(team_name)

            # 2. 👑 팀 전용 킥 권한(오버라이드) 세팅
            overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True), # 일반인은 접속 가능
            role: discord.PermissionOverwrite(
                manage_channels=True,  # 방 이름 변경, 인원수 제한 등 채널 자체 관리 권한
                move_members=True,     # 다른 통화방으로 이동 및 연결 끊기(킥) 권한
                mute_members=True,     # 상대방 마이크 강제 음소거 권한
                deafen_members=True    # 상대방 헤드셋 강제 뮤트 권한
            )
        }
                
            # 3. 🔊 보이스 채널 복구 및 권한 부여
            channel_name = f"🔊-{team_name}"
            existing_channel = discord.utils.get(guild.voice_channels, name=channel_name)
            
            if not existing_channel:
                # 채널이 없으면 권한을 씌워서 새로 만듦
                await guild.create_voice_channel(name=channel_name, category=category, overwrites=overwrites)
                created_channels.append(team_name)
            else:
                # 이미 채널이 있다면 기존 채널에 킥 권한만 업데이트!
                await existing_channel.set_permissions(role, move_members=True)
                updated_perms.append(team_name)
                
            # 4. 👥 해당 팀원들에게 역할 일괄 지급
            for d_id in player_ids:
                member = guild.get_member(int(d_id))
                if not member:
                    try:
                        member = await guild.fetch_member(int(d_id))
                    except discord.NotFound:
                        continue
                
                if member and role not in member.roles:
                    await member.add_roles(role)
                    assigned_count += 1

        # 5. 결과 보고서
        msg = "✅ **기존 팀 통화방, 역할, 킥 권한 동기화 완료!**\n"
        if created_channels:
            msg += f"- 🔊 **새로 생성된 통화방:** {', '.join(created_channels)}\n"
        if updated_perms:
            msg += f"- 👑 **킥 권한이 부여된 기존 방:** {', '.join(updated_perms)}\n"
        if created_roles:
            msg += f"- 🏷️ **새로 생성된 역할:** {', '.join(created_roles)}\n"
        if assigned_count > 0:
            msg += f"- 👥 **역할을 지급받은 팀원 수:** 총 {assigned_count}명\n"

        await interaction.followup.send(msg)

    except discord.Forbidden:
        await interaction.followup.send("❌ 봇의 권한이 부족합니다! 봇의 역할을 최상단으로 올리고, '역할 관리' 및 '채널 관리' 권한을 주세요.")
    except Exception as e:
        await interaction.followup.send(f"❌ 시스템 오류 발생: {e}")

# ==========================================
# /팀삭제 슬래시 명령어 (팀 완전 해체 및 전원 FA 전환)
# ==========================================
@bot.tree.command(name="팀삭제", description="본인이 속한 팀을 완전히 해체합니다. (팀원 전원 FA 전환 및 채널 폭파)")
async def delete_team_slash(interaction: discord.Interaction):
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 시장이 종료되어 더 이상 팀을 해체할 수 없습니다.", ephemeral=True)
        return

    user_id = str(interaction.user.id)

    @sync_to_async
    def process_delete_team(d_id):
        from django.db import close_old_connections
        close_old_connections()
        from tournament.models import Player
        try:
            player = Player.objects.get(discord_user_id=d_id)
            if not player.team:
                return False, "❌ 소속된 팀이 없어 해체할 수 없습니다."
            
            team = player.team
            team_name = team.name

            if team.leader_discord_id and team.leader_discord_id != d_id:
                return False, f"❌ 권한 없음: **{team_name}** 팀을 최초로 창단한 '팀장'만 팀을 해체할 수 있습니다."
            
            # 1. 팀에 속한 모든 유저를 무소속(FA)으로 변경
            players_in_team = team.players.all()
            member_riot_ids = [p.riot_id for p in players_in_team] # 해체 알림을 위해 이름들 저장
            
            for p in players_in_team:
                p.team = None
                p.save()
            
            # 2. 팀 DB 폭파
            team.delete()
            
            return True, (team_name, member_riot_ids)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    # 봇 생각할 시간 벌기
    await interaction.response.defer()

    success, result = await process_delete_team(user_id)

    if success:
        team_name, member_riot_ids = result
        guild = interaction.guild
        
        # ==========================================
        # 🚨 삭제된 팀의 임시 통화방 & 역할 자동 폭파!
        # ==========================================
        # 1) 채널 삭제
        channel_to_delete = discord.utils.get(guild.voice_channels, name=f"🔊-{team_name}")
        if channel_to_delete:
            try:
                await channel_to_delete.delete()
            except Exception as e:
                print(f"채널 삭제 오류: {e}")
        
        # 2) 역할(Role) 삭제 (역할을 지우면 멤버들에게서도 자동으로 다 사라짐!)
        role_to_delete = discord.utils.get(guild.roles, name=team_name)
        if role_to_delete:
            try:
                await role_to_delete.delete()
            except Exception as e:
                print(f"역할 삭제 오류: {e}")

        # 폭파 성공 메시지 전송
        embed = discord.Embed(title="💥 팀 공식 해체", color=0xE74C3C)
        embed.description = f"**{team_name}** 팀이 공식적으로 해체되었습니다."
        embed.add_field(
            name="[ FA 전환 명단 ]", 
            value=", ".join(member_riot_ids) if member_riot_ids else "없음", 
            inline=False
        )
        embed.set_footer(text="해당 팀의 통화방과 역할이 모두 삭제되었습니다. 참가자들은 새로운 팀에 가입해 주세요.")
        
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(result, ephemeral=True)

# ==========================================
# /공지배포 슬래시 명령어 (관리자 전용) - 최종 룰북 & 배너 가이드 포함
# ==========================================
@bot.tree.command(name="공지배포", description="[관리자 전용] 공식 채널에 시스템 봇 이름으로 공지사항 및 가이드를 배포합니다.")
@app_commands.describe(notice_type="배포할 공지 종류를 선택하세요")
@app_commands.choices(notice_type=[
    app_commands.Choice(name="1. 메인 공지 및 스케줄", value="schedule"),
    app_commands.Choice(name="2. 공식 대회 룰북 (토너먼트 반영)", value="rules"),
    app_commands.Choice(name="3. 웹사이트 링크", value="website"),
    app_commands.Choice(name="4. [가이드] 팀 가입 방법 (배너 포함)", value="guide_join"),
    app_commands.Choice(name="5. [가이드] 결과 제출 방법 (배너 포함)", value="guide_submit"),
    app_commands.Choice(name="6. 봇 사용법 공지", value="bot_guide"),
    app_commands.Choice(name="7. [가이드] 자기소개 작성 방법", value="guide_intro"),
    app_commands.Choice(name="8. [필독] 참가비 납부 안내", value="fee_notice"),
    app_commands.Choice(name="9. [업데이트] 시스템 봇 패치 노트", value="bot_update"),
])
@app_commands.default_permissions(administrator=True)
async def send_official_notice(interaction: discord.Interaction, notice_type: str):
    
    embed_color = 0x6C85DE 
    TEAM_SIGNUP_IMG_URL = "https://i.imgur.com/jjUufqx.png"
    SUBMIT_RESULT_IMG_URL = "https://i.imgur.com/JB1zLCU.png"

    if notice_type == "schedule":
        embed = discord.Embed(
            title="[ 2026 TÆKTUBE INVITATIONAL ]",
            description="**MONTREAL EDITION S1**\n\n본 대회는 주최자의 개인적인 만족을 위해 기획되었습니다.\n모든 참가자는 시스템의 통제에 따라야 하며, 웹사이트와 디스코드 봇을 통해 일정이 관리됩니다.",
            color=embed_color
        )
        embed.add_field(
            name="[ OFFICIAL SCHEDULE ]", 
            value=(
                "- **03.09 (화) 23:59** | 선수 등록 마감 (총 30명 선착순 조기 마감 가능)\n"
                "- **03.10 (화) ~**     | 공식 스크림 기간 시작\n"
                "- **03.21 (토) 23:59** | 팀 로스터 확정 (이적 시장 종료 & 조 추첨)\n"
                "- **03.28 (토) 22:00** | Group Stage (A/B조 단판 풀리그) & 데스매치\n"
                "- **03.29 (일) 21:00** | Semi Final (4강전)\n"
                "- **T.B.D** | Grand Final (결승전 - 추후 공지)"
            ), 
            inline=False
        )
        embed.set_footer(text="* STRICTLY FOR PERSONAL SATISFACTION")

    elif notice_type == "bot_guide":
        embed = discord.Embed(
            title="[ SYSTEM GUIDE: BOT COMMANDS ]",
            description=(
                "본 대회의 팀 로스터 등록 및 경기 결과 제출은 **100% 봇 명령어를 통해 자동화**되어 있습니다.\n"
                "시스템 사용법에 대한 문의나 예기치 못한 버그 발생 시, 즉시 관리자(<@286566325231288323>)를 호출해 주십시오."
            ),
            color=embed_color
        )
        embed.add_field(
            name="[ 1. TEAM ROSTER MANAGEMENT (팀 창단/가입/방출) ]", 
            value=(
                "📍 **채널:** <#1477537891214426262> (이동 클릭)\n"
                "🆕 **팀 창단:** `/팀생성` (원하는 팀 이름 입력, 최대 6팀)\n"
                "🤝 **팀 가입:** `/팀가입` (자동완성 리스트에서 기존 팀 선택)\n"
                "🚷 **팀원 방출:** `/팀원추방` (같은 팀원을 강제 FA 전환)\n"
                "- 이적 시장 마감 전까지 자유로운 이적(탕치기)과 방출이 허용됩니다."
            ), 
            inline=False
        )
        embed.add_field(
            name="[ 2. RESULT SUBMISSION (결과 제출) ]", 
            value=(
                "📍 **채널:** <#1477537918817013760> (이동 클릭)\n"
                "⌨️ **명령어:** `/결과제출` (승리 팀, 경기 시간, **승리 화면 스크린샷** 첨부 필수)\n"
                "🚨 **[다전제 룰]** 세미파이널(Bo3)과 결승전(Bo5)은 시리즈 종료 후가 아닌, **'매 세트가 종료될 때마다'** 결과를 제출해야 스코어가 정상적으로 누적됩니다."
            ), 
            inline=False
        )
        
    elif notice_type == "rules":
        embed = discord.Embed(
            title="[ TOURNAMENT RULEBOOK ]",
            description="원활한 대회 진행을 위한 공식 시스템 규정입니다. 미숙지로 인한 불이익은 전적으로 본인에게 있습니다.",
            color=embed_color
        )
        embed.add_field(
            name="01. TOURNAMENT BRACKET | 대진표 및 진출 시스템", 
            value=(
                "모든 팀은 무작위 조 추첨을 통해 A조 또는 B조에 배정되어 단판 풀리그(Bo1)를 치릅니다.\n\n"
                "⚔️ **[ Deathmatch (Quarter-Finals) - Bo1 ]**\n"
                "- **DM 1:** A조 2위 vs B조 3위\n"
                "- **DM 2:** B조 2위 vs A조 3위\n\n"
                "🌟 **[ Semi-Finals (4강전) - Bo3 ]**\n"
                "- **SF 1:** B조 1위 (직행) vs **DM 1 승자**\n"
                "- **SF 2:** A조 1위 (직행) vs **DM 2 승자**\n\n"
                "🏆 **[ Grand Final (결승전) - Bo5 ]**\n"
                "- **SF 1 승자** vs **SF 2 승자**"
            ), 
            inline=False
        )
        embed.add_field(
            name="02. TIE-BREAKERS | 조별 순위 결정 규칙", 
            value=(
                "- 조별 리그 순위는 다음 순서로 산정됩니다: 1순위 다승(Wins) | 2순위 승자승(Head-to-Head) | 3순위 스피드런(평균 최단 승리 시간).\n"
                "- 3팀이 모두 1승 1패로 동률일 경우, 즉시 '스피드런' 랭킹으로 결정되며 가장 짧은 시간에 승리한 팀이 상위 순위를 차지합니다."
            ), 
            inline=False
        )
        embed.add_field(
            name="03. ACCOUNT INTEGRITY | 계정 원칙", 
            value="- 반드시 본 계정만 사용해야 합니다. 부계정(Smurf) 적발 시 즉각 실격되며 환불은 불가합니다.\n* [ EX ] 대리 게임 또는 의심 사례 발생 시 운영진이 디스코드 화면 공유 등으로 본인 인증을 요구할 수 있습니다.", 
            inline=False
        )
        embed.add_field(
            name="04. PUNCTUALITY | 지각 규정", 
            value="- 경기 5분 전 지정 로비 및 보이스 접속 필수.\n- 지각 시 5분 단위로 밴 카드 1장씩 압수되며, 15분 이상 지각 시 해당 팀은 실격(Auto DQ) 처리됩니다.\n* [ EX ] 20:00 경기일 경우, 20:05~20:09 도착 시 밴 카드 1장 압수.", 
            inline=False
        )
        embed.add_field(
            name="05. CONDUCT | 매너 및 채팅", 
            value="- 도발이나 감정 표현은 허용되나, 타인에게 직접적인 욕설은 엄격히 금지합니다.\n- 상대 팀의 중단 요청(Respect the Ask) 시 즉각 수용해야 합니다.\n- 누적 2회 경고 후에도 지속될 경우(Three Strikes) 팀 전체가 퇴출됩니다.", 
            inline=False
        )
        embed.add_field(
            name="06. TECHNICAL PAUSE | 퍼즈 규정", 
            value="- 인터넷 및 하드웨어 등 합당한 문제 발생 시에만 허용되며, 경기당 팀별 최대 10분으로 엄격히 제한됩니다.\n* [ EX ] 핑 문제, 마우스 연결 끊김 등. 단, 화장실이나 담배 타임 목적의 퍼즈는 절대 불가합니다.", 
            inline=False
        )
        embed.add_field(
            name="07. COMMUNICATION | 소통 및 운영", 
            value="- 게임 중에는 팀 전체가 배정된 음성 채널에 들어가 있어야 합니다.\n- 관전자는 마이크 사용이 절대 금지됩니다.\n- 문제 발생 및 이의 제기 시 시스템 관리자(`JYPIMNIDA`)에게 즉각 연락하십시오.", 
            inline=False
        )
        embed.add_field(
            name="08. REGISTRATION & FEES | 등록 및 환불", 
            value="- 등록 마감 후 참가 비용이 청구될 예정입니다.\n- 룰 위반 및 지각 등으로 인한 실격 시 어떠한 경우에도 환불은 없습니다.", 
            inline=False
        )
        embed.add_field(
            name="09. FEARLESS DRAFT | 피어리스 밴픽", 
            value="- 다전제(Bo3, Bo5) 진행 시, 이전 세트에서 한 번이라도 등장한(픽된) 챔피언은 해당 매치의 남은 세트 동안 **양 팀 모두** 다시 선택할 수 없습니다.\n* [ EX ] 1세트에서 A팀이 '아리'를 픽했다면, 이어지는 2, 3세트에서는 A팀과 B팀 모두 '아리'를 사용할 수 없습니다.", 
            inline=False
        )
        embed.add_field(
            name="10. ORGANIZER'S NOTE | 운영자 유의사항", 
            value="- 참가자와 운영진 모두 프로 선수가 아닙니다. 상호 존중을 지켜주시고 시스템의 통제에 따라주십시오.", 
            inline=False
        )
        
    elif notice_type == "website":
        embed = discord.Embed(
            title="[ OFFICIAL PLATFORM ]",
            description="대회의 모든 데이터는 아래 웹사이트에서 실시간으로 동기화됩니다.\n질문하기 전에 웹사이트를 먼저 확인하십시오.",
            color=embed_color
        )
        embed.set_image(url="https://i.imgur.com/LEqBZ9y.png")
        embed.add_field(name="[ LINK ]", value="https://taektube.lol/", inline=False) 
        embed.add_field(
            name="[ SYSTEM TRACKING ]", 
            value="- 실시간 대진표 및 토너먼트 진행 상황\n- A조/B조 랭킹 보드\n- 참가자별 티어 및 포지션 분포표", 
            inline=False
        )

    elif notice_type == "guide_join":
        embed = discord.Embed(
            title="[ SYSTEM GUIDE: TEAM CREATION & SIGN-UP ]",
            description="참가자는 직접 새로운 팀을 창단하거나 기존 팀에 합류할 수 있으며, 치열한 이적 시장 규정을 따릅니다.",
            color=embed_color
        )
        embed.add_field(
            name="[ 1. 새로운 팀 창단하기 ]",
            value="💬 채팅창에 `/팀생성 [원하는 팀 이름]`을 입력하세요.\n- 본인이 해당 팀의 팀장(첫 번째 멤버)으로 자동 등록되며, 대회 규정상 총 **6개 팀**까지만 창단이 가능합니다.",
            inline=False
        )
        embed.add_field(
            name="[ 2. 기존 팀 가입 및 이적 ]",
            value="💬 채팅창에 `/팀가입`을 입력하고 리스트에서 팀을 선택하세요.\n- 선택한 팀의 정원(5명)이 꽉 차지 않았다면 즉시 합류됩니다.",
            inline=False
        )
        embed.add_field(
            name="[ 3. 팀원 방출 (FA 전환) ]",
            value="💬 채팅창에 `/팀원추방`을 입력하고 방출할 팀원을 멘션하세요.\n- 같은 팀에 속한 멤버만 방출할 수 있으며, 방출된 인원은 즉시 무소속이 됩니다.",
            inline=False
        )
        embed.add_field(
            name="[ 유의사항 ]",
            value="- 이적 시장 마감일(03.21) 전까지는 무제한 탕치기와 강제 방출이 허용됩니다.\n- 마감 이후에는 로스터가 완전히 고정되며, 각 팀별 프라이빗 작전 회의실이 오픈됩니다.",
            inline=False
        )

    elif notice_type == "guide_submit":
        embed = discord.Embed(
            title="[ SYSTEM GUIDE: RESULT SUBMISSION ]",
            description="경기가 종료되면 승리 팀은 즉시 시스템에 결과를 보고해야 합니다.",
            color=embed_color
        )
        embed.add_field(
            name="[ 명령어 사용법 ]",
            value="💬 지정된 결과 제출 채널에서 `/결과제출` 명령어를 사용하세요.\n승리한 팀 이름, 경기 시간(MM:SS), 그리고 **승리 화면 스크린샷** 첨부가 필수입니다.",
            inline=False
        )
        embed.add_field(
            name="[ 다전제 (Bo3 / Bo5) 제출 룰 ] 🚨 필수 숙지",
            value="- 조별 리그 및 데스매치는 1경기 종료 후 1회 제출합니다.\n- **세미파이널과 결승전은 '매 세트가 끝날 때마다' 결과를 제출하십시오.**\n- 시스템이 자동으로 스코어를 누적 계산하여 최종 승자를 판별합니다.",
            inline=False
        )

    elif notice_type == "guide_intro":
        embed = discord.Embed(
            title="[ SYSTEM GUIDE: SELF-INTRODUCTION ]",
            description="참가자들의 원활한 소통과 팀 빌딩을 위해 시스템에 자신을 등록해 주십시오.",
            color=embed_color
        )

        embed.add_field(
            name="[ 명령어 사용법 ]",
            value="💬 채팅창에 `/자기소개`를 입력하고, 나타나는 5가지 필수 항목을 모두 채워 제출하세요.",
            inline=False
        )
        embed.add_field(
            name="[ 입력 항목 안내 ]",
            value=(
                "- **riot_id:** 정확한 롤 닉네임 (예: Hide on bush#KR1)\n"
                "- **positions:** 주 포지션 및 가능 포지션 (예: 미드/원딜 가능)\n"
                "- **current_tier:** 현재 솔로 랭크 티어\n"
                "- **highest_tier:** 본인 역대 최고 티어\n"
                "- **appeal:** 팀원들에게 어필할 자유로운 한마디"
            ),
            inline=False
        )
        embed.add_field(
            name="[ 유의사항 ]",
            value="- 이 데이터는 팀장들의 스카우트와 이적 시장(탕치기)의 중요한 지표가 됩니다.\n- 모든 참가자가 열람하는 공간이므로, 욕설이나 부적절한 언행은 삼가 주시기 바랍니다.",
            inline=False
        )

    elif notice_type == "fee_notice":
        embed = discord.Embed(
            title="[ SYSTEM NOTICE: ENTRY FEE ]",
            description="대회 상금 풀 조성 및 원활한 시스템 운영을 위한 참가비 납부 안내입니다.\n3.14 전까지 **무조건 납부를 완료**해야 참가 자격이 유지됩니다.",
            color=0xF1C40F # 경고/안내 느낌을 주는 쨍한 옐로우
        )

        embed.add_field(
            name="[ 🗓️ 납부 기한 ]",
            value="**최대한 빨리 납부 요망!** (3.14까지 필수)\n -참가비: 15 CAD",
            inline=False
        )
        embed.add_field(
            name="[ 🇨🇦 몬트리올 / 캐나다 거주자 ]",
            value="**💳 E-Transfer:** `priceisbest@gmail.com`",
            inline=False
        )
        embed.add_field(
            name="[ 🇺🇸 북미 (미국 등) 거주자 ]",
            value=(
                "**💳 PayPal:** `priceisbest@hotmail.com`"
            ),
            inline=False
        )
        embed.add_field(
            name="[ 🚨 필수 유의사항 ]",
            value="- 송금 시 메모(Message)란에 반드시 **디스코드 닉네임** 또는 **롤 닉네임**을 기재해 주십시오.\n- 미납 시 팀 확정 명단에서 강제 제외(FA)되며 대회 참여가 취소될 수 있습니다.",
            inline=False
        )
        embed.set_footer(text="* 입금 확인 시 관리자가 수동으로 시스템에 반영합니다.")

    elif notice_type == "bot_update":
        embed = discord.Embed(
            title="🤖 [ SYSTEM UPDATE: V2.1 TEAM RENAME ]",
            description="이적 시장 기간 동안 소속 팀의 이름을 자유롭게 변경할 수 있는 신규 기능이 탑재되었습니다.",
            color=0x2ECC71
        )
        
        embed.add_field(
            name="🏷️ [ 신규 명령어: /팀명변경 ]",
            value=(
                "- **사용법:** 채팅창에 `/팀명변경 [새로운 팀명]`을 입력하세요. (최대 50자이지만, 너무 길지 않게 부탁드립니다.)\n"
                "- **사용 권한:** 방장뿐만 아니라 **소속 팀원이라면 누구나** 명령어를 사용할 수 있습니다."
            ),
            inline=False
        )
        
        embed.add_field(
            name="🚨 [ 필수 주의사항 & 예외 처리 ]",
            value=(
                "- 해당 명령어는 기본적으로 **로스터 확정(이적 시장 마감) 전까지만** 사용할 수 있습니다.\n"
                "- 마감 이후에는 시스템 상 팀 이름이 고정(Lock)되나, **불가피하게 팀명 변경이 필요한 경우 관리자에게 개별 문의**해 주시면 상의 후 예외적으로 처리해 드리겠습니다."
            ),
            inline=False
        )
        
        embed.set_footer(text="* 팀확정까지 시간이 얼마 남지 않았습니다. 팀가입 및 팀명 설정을 서둘러주세요!")

    # 봇이 메시지를 보내기 전에 생각할 시간 벌기
    await interaction.response.defer(ephemeral=True)

    try:
        await interaction.channel.send(embed=embed)
        await interaction.followup.send("✅ 시스템 봇이 해당 채널에 오피셜 공지/가이드를 배포했습니다.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 메시지 전송 실패: {e}", ephemeral=True)

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))