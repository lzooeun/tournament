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
    WELCOME_CHANNEL_ID = 1477547605276754025  # 웰컴 메시지를 띄울 채널 (예: #입장-인사 또는 #잡담)
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

    riot_id = await get_player_riot_id(member.id)

    # 2. 닉네임 변경 시도
    changed_nick = False
    if riot_id:
        new_nick = riot_id[:32]
        try:
            await member.edit(nick=new_nick)
            changed_nick = True
        except Exception as e:
            print(f"❌ 닉네임 변경 실패: {e}")

    # 3. 웰컴 메시지 전송
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        embed = discord.Embed(
            title="🎉 신규 참가자 입장!",
            description=f"환영합니다, <@{member.id}>님! 2026 TÆKTUBE INVITATIONAL에 합류하셨습니다.",
            color=0x6C85DE
        )
        
        if changed_nick:
            embed.description += f"\n*(시스템에 의해 별명이 `{new_nick}`으로 자동 변경되었습니다.)*"

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
        embed.add_field(
            name="[ STEP 3 ] 역할 선택 (필수)",
            value="아래 이모지를 클릭하여 서버 접근 권한을 획득하세요.\n⚔️ : **참가자** (선수 등록 및 로스터 관리 가능)\n🍿 : **관전자** (공용 채널 열람 및 각 팀 보이스 청취 가능)",
            inline=False
        )
        
        msg = await welcome_channel.send(content=f"<@{member.id}>", embed=embed)
        await msg.add_reaction("⚔️")
        await msg.add_reaction("🍿")


# ==========================================
# [ 이벤트 ] 유저가 리액션(이모지)을 눌렀을 때 (참가자 vs 관전자)
# ==========================================
@bot.event
async def on_raw_reaction_add(payload):
    if payload.member.bot:
        return

    WELCOME_CHANNEL_ID = 1477547605276754025 # 웰컴 채널 ID 확인!

    if payload.channel_id == WELCOME_CHANNEL_ID:
        guild = bot.get_guild(payload.guild_id)
        role_name = None

        if str(payload.emoji) == "⚔️":
            role_name = "참가자"
        elif str(payload.emoji) == "🍿":
            role_name = "관전자"

        if role_name:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                await payload.member.add_roles(role)
                print(f"✅ {payload.member.name} 님에게 '{role_name}' 역할이 부여되었습니다.")
            else:
                print(f"❌ '{role_name}' 역할을 서버에서 찾을 수 없습니다.")

# ==========================================
# 팀 이름 자동완성 함수
# ==========================================
async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    @sync_to_async
    def get_teams():
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
        
        embed = discord.Embed(title="🤝 팀 이적 완료!", color=0x2ecc71)
        embed.description = f"**{riot_id}** 님이 팀을 이동했습니다."
        embed.add_field(name="이전 소속", value=old_team, inline=True)
        embed.add_field(name="➡️", value=" ", inline=True)
        embed.add_field(name="새로운 소속", value=f"**{new_team}**", inline=True)
        
        # 💥 폭파된 팀이 있다면 추가 알림!
        if deleted_team:
            embed.add_field(
                name="💥 팀 해체 알림", 
                value=f"**{deleted_team}** 팀에 남은 멤버가 없어 시스템에 의해 자동 해체(삭제)되었습니다. (새로운 팀 창단 가능)", 
                inline=False
            )
            
        embed.set_footer(text="웹사이트의 Team List에 즉각 반영되었습니다.")
        
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(result, ephemeral=True)

# ==========================================
# /팀확정 슬래시 명령어 (관리자 전용) - 카테고리/채널 자동 생성 포함
# ==========================================
TEAM_JOIN_LOCKED = False 

@bot.tree.command(name="팀확정", description="[관리자 전용] 팀선택 마감, 역할 부여 및 팀별 비밀 채널을 자동 생성합니다.")
@app_commands.default_permissions(administrator=True)
async def confirm_teams_slash(interaction: discord.Interaction):
    global TEAM_JOIN_LOCKED
    
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ 이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    await interaction.response.defer()

    # DB에서 팀과 해당 팀원들의 디스코드 ID 가져오기
    @sync_to_async
    def get_teams_and_players():
        from tournament.models import Team
        teams = list(Team.objects.prefetch_related('players').all())
        team_data = []
        for t in teams:
            p_ids = [p.discord_user_id for p in t.players.all()]
            team_data.append((t.name, p_ids))
        return team_data

    try:
        teams_data = await get_teams_and_players()
        log_msgs = []

        for team_name, player_ids in teams_data:
            # 1. 역할(Role) 확인 및 생성
            role = discord.utils.get(guild.roles, name=team_name)
            if not role:
                role = await guild.create_role(
                    name=team_name, 
                    hoist=True, 
                    mentionable=True, 
                    reason="TÆKTUBE 팀 확정 자동 생성"
                )
                log_msgs.append(f"✨ `{team_name}` 역할 생성 완료")

            # 2. 팀원들에게 역할 부여
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
            
            log_msgs.append(f"👥 `{team_name}` {assigned_count}명 역할 부여 완료")

            # ==========================================
            # 🎯 3. 프라이빗 카테고리 & 채널 자동 생성 파트 (관전자 로직 추가)
            # ==========================================
            category_name = f"[ {team_name} ]"
            category = discord.utils.get(guild.categories, name=category_name)
            spectator_role = discord.utils.get(guild.roles, name="관전자")
            
            # [ 기본 권한 ]: @everyone(기본)은 못 보고, '팀원'은 다 할 수 있음
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
                role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, send_messages=True)
            }

            if not category:
                # 1. 카테고리 & 채팅방 생성 (이때 관전자는 권한이 없으므로 채팅방 절대 못 봄)
                category = await guild.create_category(name=category_name, overwrites=overwrites)
                await guild.create_text_channel(name="전략-회의", category=category)
                
                # 2. 보이스 채널 전용 권한 세팅 (팀원 권한 + 관전자 '듣기 전용' 권한)
                vc_overwrites = overwrites.copy()
                if spectator_role:
                    # 🚨 관전자: 채널 보임(True), 접속 가능(True), 말하기 불가(False)!
                    vc_overwrites[spectator_role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=False)
                
                # 3. 보이스 채널 생성 (관전자 덮어쓰기 적용)
                await guild.create_voice_channel(name="🔊-보이스", category=category, overwrites=vc_overwrites)
                
                log_msgs.append(f"📁 `{team_name}` 비밀 채널 세팅 완료 (관전자 듣기 허용)")

        # 4. 탕치기 잠금 스위치 ON
        TEAM_JOIN_LOCKED = True

        # 5. 결과창 띄우기
        result_text = "\n".join(log_msgs)
        embed = discord.Embed(title="🔒 팀 확정 & 채널 세팅 완료!", color=0xE74C3C)
        embed.description = (
            f"**이적 시장이 종료되었으며, 각 팀의 비밀 작전실이 오픈되었습니다.**\n"
            f"더 이상 `/팀가입`을 사용할 수 없습니다.\n\n"
            f"**[처리 결과]**\n{result_text}"
        )
        embed.set_footer(text="참가자들은 본인 팀의 채널이 잘 보이는지 확인해 주세요!")
        
        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.followup.send("❌ 봇에게 권한이 부족합니다! 서버 설정에서 봇의 역할을 최상단으로 올리고, '채널 관리' 및 '역할 관리' 권한을 주세요.")
    except Exception as e:
        await interaction.followup.send(f"❌ 오류 발생: {str(e)}")

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
# /팀생성 슬래시 명령어 (참가자 직접 창단)
# ==========================================
@bot.tree.command(name="팀생성", description="새로운 팀을 창단하고 해당 팀의 첫 번째 멤버로 등록됩니다.")
@app_commands.describe(team_name="창단할 팀의 이름을 입력하세요 (최대 15자)")
async def create_team_slash(interaction: discord.Interaction, team_name: str):
    # 팀 가입 채널과 동일한 곳에서 사용하도록 제한
    if interaction.channel_id != TEAM_JOIN_CHANNEL_ID:
        await interaction.response.send_message(f"❌ 이 명령어는 <#{TEAM_JOIN_CHANNEL_ID}> 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 및 창단 기간이 마감되어 새로운 팀을 만들 수 없습니다.", ephemeral=True)
        return

    # 글자 수 제한 (디스코드 역할 이름 길이 제한 등 UI/UX 고려)
    if len(team_name.strip()) > 15:
        await interaction.response.send_message("❌ 팀 이름은 공백 포함 최대 15자까지만 가능합니다.", ephemeral=True)
        return

    user_id = str(interaction.user.id)

    @sync_to_async
    def process_create_team(d_id, t_name):
        from tournament.models import Player, Team
        try:
            # 1. 디스코드 ID로 참가자 확인
            player = Player.objects.get(discord_user_id=d_id)
            
            # 2. 팀 이름 중복 검사 (대소문자 무시하고 일치하는지 확인)
            if Team.objects.filter(name__iexact=t_name).exists():
                return False, f"❌ **{t_name}** (이)라는 이름의 팀이 이미 존재합니다. 다른 이름을 골라주세요."
            
            # 3. 최대 팀 개수 제한 (대회 규모 6팀으로 제한)
            if Team.objects.count() >= 6:
                return False, "❌ 이미 6개의 팀이 모두 창단되었습니다! 기존에 만들어진 팀에 `/팀가입` 해주세요."

            # 4. 팀 생성 및 유저 자동 할당
            new_team = Team.objects.create(name=t_name)
            player.team = new_team
            player.save()
            
            return True, (player.riot_id, new_team.name)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다. 주최자에게 먼저 등록을 요청하세요."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    # 봇이 생각할 시간 벌기
    await interaction.response.defer()
    
    # DB 처리 함수 실행
    success, result = await process_create_team(user_id, team_name.strip())
    
    if success:
        riot_id, new_team_name = result
        
        # 빰빠빰! 성공 임베드 메시지
        embed = discord.Embed(title="🎊 신규 팀 창단 완료!", color=0xF1C40F) # 빛나는 황금색
        embed.description = f"**{riot_id}** 님이 새로운 팀을 창단했습니다!"
        embed.add_field(name="[ 팀 이름 ]", value=f"**{new_team_name}**", inline=False)
        embed.add_field(
            name="[ 안내 ]", 
            value=f"이제 다른 참가자들이 `/팀가입` 명령어의 자동완성 리스트에서 **{new_team_name}**을 찾아 가입할 수 있습니다.", 
            inline=False
        )
        embed.set_footer(text="팀장님, 멋진 로스터를 꾸려 우승을 차지해 보세요!")
        
        await interaction.followup.send(embed=embed)
    else:
        # 실패 시 에러 메시지 (본인에게만 보임)
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
        
        embed = discord.Embed(title="🚨 팀원 방출 (FA 전환)", color=0xE74C3C)
        embed.description = f"**{target_riot_id}** 님이 **{team_name}** 팀에서 방출되었습니다."
        
        # 💥 1명 남은 팀장이 다른 팀원을 다 쫓아내고, 마지막으로 남은 한 명마저 쫓겨나서 팀이 비어버릴 경우 대비
        if deleted_team:
            embed.add_field(
                name="💥 팀 해체 알림", 
                value=f"해당 방출로 인해 **{deleted_team}** 팀의 인원이 0명이 되어 자동 해체(삭제)되었습니다.", 
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
                "- **03.28 (토) 21:00** | Group Stage (A/B조 단판 풀리그) & 데스매치\n"
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
            description="대회 상금 풀 조성 및 원활한 시스템 운영을 위한 참가비 납부 안내입니다.\n팀 로스터 확정(03.21) 전까지 **무조건 납부를 완료**해야 참가 자격이 유지됩니다.",
            color=0xF1C40F # 경고/안내 느낌을 주는 쨍한 옐로우
        )

        embed.add_field(
            name="[ 🗓️ 납부 기한 ]",
            value="**최대한 빨리 납부 요망!** (3.14까지 필수)",
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