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

app = Flask('')

@app.route('/')
def home():
    return "I'm alive!"

def run():
    # Koyeb은 기본적으로 8080 포트를 체크함
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# 2. 봇 기본 설정
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 3. 봇이 켜졌을 때 슬래시 명령어 동기화!
@bot.event
async def on_ready():
    # 디스코드 서버에 우리가 만든 슬래시 명령어들을 등록하는 작업이야
    await bot.tree.sync() 
    print(f'✅ 봇 로그인 성공: {bot.user.name}')
    print('✅ 슬래시 명령어 동기화 완료!')

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

# ==========================================
# /결과입력 슬래시 명령어
# ==========================================
@bot.tree.command(name="결과입력", description="진행된 경기의 승리 팀과 소요 시간을 입력합니다.")
@app_commands.describe(
    team_name="어느 팀이 이겼나요? (목록에서 선택하세요)",
    duration="게임 소요 시간을 '분:초' 형식으로 적어주세요 (예: 30:15)"
)
@app_commands.autocomplete(team_name=team_autocomplete) # 자동완성 연결!
async def enter_result_slash(interaction: discord.Interaction, team_name: str, duration: str):
    
    # 시간 포맷 검증
    if not re.match(r'^\d{1,2}:\d{2}$', duration):
        # 슬래시 명령어는 ctx.send 대신 interaction.response.send_message를 써야 해!
        await interaction.response.send_message("❌ 시간은 `분:초` 형식으로 정확히 적어주세요! (예: `30:15`)", ephemeral=True)
        return

    @sync_to_async
    def process_match_result(t_name, game_time):
        try:
            winner_team = Team.objects.get(name=t_name)
            
            pending_match = Match.objects.filter(
                Q(team_a=winner_team) | Q(team_b=winner_team),
                status='PENDING'
            ).order_by('match_number').first()

            if not pending_match:
                return False, f"❌ '{t_name}' 팀이 치를 대기 중인 경기가 없습니다."

            loser_team = pending_match.team_b if pending_match.team_a == winner_team else pending_match.team_a

            pending_match.status = 'COMPLETED'
            pending_match.winner = winner_team
            pending_match.game_duration = game_time
            pending_match.save()

            winner_team.wins += 1
            winner_team.save()

            loser_team.losses += 1
            loser_team.save()

            return True, (pending_match.match_number, winner_team.name, loser_team.name, game_time)

        except Team.DoesNotExist:
            return False, f"❌ '{t_name}' 팀을 DB에서 찾을 수 없습니다."
        except Exception as e:
            return False, f"❌ 오류 발생: {str(e)}"

    # 봇이 처리하는 동안 '생각 중...' 메시지를 띄움
    await interaction.response.defer()
    
    success, result = await process_match_result(team_name, duration)
    
    if success:
        match_num, w_name, l_name, g_time = result
        
        embed = discord.Embed(title=f"Game {match_num} 결과 저장 완료!", color=0x7289DA) 
        embed.add_field(name="🏆 승리", value=f"**{w_name}**", inline=True)
        embed.add_field(name="💀 패배", value=l_name, inline=True)
        embed.add_field(name="⏱️ 소요 시간", value=g_time, inline=False)
        embed.set_footer(text="이 결과는 TÆKTUBE 웹사이트 순위표에 실시간으로 반영되었습니다.")
        
        # 처리 완료 후 임베드 전송 (defer를 썼기 때문에 followup 사용)
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(result)

# ==========================================
# /결과취소 슬래시 명령어 (관리자 전용)
# ==========================================
@bot.tree.command(name="결과취소", description="[관리자 전용] 잘못 입력된 경기 결과를 다시 대기 상태로 되돌립니다.")
@app_commands.describe(match_number="취소할 경기 번호를 숫자로 입력하세요 (예: 1)")
@app_commands.default_permissions(administrator=True) # ✨ 핵심: 관리자 권한이 있는 사람에게만 이 명령어가 보임!
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
# /팀가입 슬래시 명령어 (탕치기 기능)
# ==========================================
@bot.tree.command(name="팀가입", description="원하는 팀에 가입하거나 이동합니다.")
@app_commands.describe(team_name="가입할 팀을 선택하세요")
@app_commands.autocomplete(team_name=team_autocomplete) # 여기서도 팀 드롭다운 자동완성 적용!
async def join_team_slash(interaction: discord.Interaction, team_name: str):

    global TEAM_JOIN_LOCKED
    if TEAM_JOIN_LOCKED:
        await interaction.response.send_message("❌ 이적 기간이 마감되어 더 이상 팀을 이동할 수 없습니다.", ephemeral=True)
        return
    
    # 명령어를 친 사람의 디스코드 고유 ID (숫자 형태의 문자열)
    user_id = str(interaction.user.id)
    
    @sync_to_async
    def process_join_team(d_id, t_name):
        try:
            # 1. DB에서 이 디스코드 ID를 가진 플레이어 찾기
            player = Player.objects.get(discord_user_id=d_id)
            
            # 2. 가입하려는 팀 찾기
            target_team = Team.objects.get(name=t_name)
            
            # 3. 팀 인원수 체크 (5명이 꽉 찼는데 들어오려는 경우 차단)
            if target_team.players.count() >= 5 and player.team != target_team:
                return False, f"❌ **{target_team.name}** 팀은 이미 5명이 꽉 찼습니다! 다른 팀을 알아보세요."
            
            # 4. 이미 해당 팀인 경우
            if player.team == target_team:
                return False, f"⚠️ 이미 **{target_team.name}** 팀에 소속되어 있습니다."
            
            # 5. 이전 팀 기록 (알림 메시지용)
            old_team_name = player.team.name if player.team else "무소속"
            
            # 6. 팀 변경 및 DB 저장
            player.team = target_team
            player.save()
            
            return True, (player.riot_id, old_team_name, target_team.name)
            
        except Player.DoesNotExist:
            return False, "❌ DB에 등록된 참가자가 아닙니다. 주최자에게 디스코드 ID 등록을 요청하세요."
        except Team.DoesNotExist:
            return False, f"❌ '{t_name}' 팀을 찾을 수 없습니다."
        except Exception as e:
            return False, f"❌ 시스템 오류 발생: {str(e)}"

    # 처리 시간 대기
    await interaction.response.defer()
    
    success, result = await process_join_team(user_id, team_name)
    
    if success:
        riot_id, old_team, new_team = result
        
        # 성공 시 예쁜 임베드 메시지로 채널에 중계
        embed = discord.Embed(title="팀 선택 완료!", color=0x2ecc71) # 눈에 띄는 초록색
        embed.description = f"**{riot_id}** 님이 팀을 이동했습니다."
        embed.add_field(name="이전 소속", value=old_team, inline=True)
        embed.add_field(name="➡️", value=" ", inline=True) # 화살표 역할로 간격 띄우기
        embed.add_field(name="새로운 소속", value=f"**{new_team}**", inline=True)
        embed.set_footer(text="웹사이트의 Team List에 즉각 반영되었습니다. 새로고침 해보세요!")
        
        await interaction.followup.send(embed=embed)
    else:
        # 실패 시 에러 메시지 (ephemeral=True로 설정하면 본인에게만 메시지가 보임)
        await interaction.followup.send(result, ephemeral=True)

# ==========================================
# /팀확정 슬래시 명령어 (관리자 전용)
# ==========================================
TEAM_JOIN_LOCKED = False 

@bot.tree.command(name="팀확정", description="[관리자 전용] 팀선택을 마감하고, 팀별로 역할을 자동 생성 및 부여합니다.")
@app_commands.default_permissions(administrator=True)
async def confirm_teams_slash(interaction: discord.Interaction):
    global TEAM_JOIN_LOCKED
    
    # 1. 명령어는 무조건 서버(길드) 안에서만 써야 함 (DM 불가)
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ 이 명령어는 디스코드 서버 안에서만 사용할 수 있습니다.", ephemeral=True)
        return

    await interaction.response.defer()

    # DB에서 팀과 해당 팀원들의 디스코드 ID 가져오기
    @sync_to_async
    def get_teams_and_players():
        teams = list(Team.objects.prefetch_related('players').all())
        team_data = []
        for t in teams:
            # 팀원들의 디스코드 고유 ID 리스트 추출
            p_ids = [p.discord_user_id for p in t.players.all()]
            team_data.append((t.name, p_ids))
        return team_data

    try:
        teams_data = await get_teams_and_players()
        log_msgs = []

        for team_name, player_ids in teams_data:
            # 2. 서버에 해당 팀 이름과 똑같은 역할(Role)이 있는지 검색
            role = discord.utils.get(guild.roles, name=team_name)
            
            # 3. 역할이 없다면 봇이 즉석에서 새로 생성
            if not role:
                role = await guild.create_role(
                    name=team_name, 
                    hoist=True, # 우측 멤버 목록에 그룹으로 묶어서 보여주기
                    mentionable=True, # @팀이름 으로 멘션 가능하게 하기
                    reason="TÆKTUBE 탕치기 마감 자동 생성"
                )
                log_msgs.append(f"✨ `{team_name}` 역할을 새로 생성했습니다.")

            # 4. 해당 팀원들에게 역할 부여하기
            assigned_count = 0
            for d_id in player_ids:
                # 디스코드 ID로 서버 내의 유저 객체 찾기
                member = guild.get_member(int(d_id))
                if not member:
                    try:
                        # 봇이 유저를 못 찾으면 서버에서 강제로 검색해서 데려오기
                        member = await guild.fetch_member(int(d_id))
                    except discord.NotFound:
                        continue # 이 서버에 없는 유저면 패스
                
                # 유저에게 아직 이 역할이 없다면 부여
                if member and role not in member.roles:
                    await member.add_roles(role)
                    assigned_count += 1
            
            log_msgs.append(f"`{team_name}` 소속 {assigned_count}명에게 역할을 부여했습니다.")

        # 5. 탕치기 잠금 스위치 ON
        TEAM_JOIN_LOCKED = True

        # 6. 결과창(Embed) 예쁘게 띄우기
        result_text = "\n".join(log_msgs)
        embed = discord.Embed(title="🔒 팀 확정 및 역할 부여 완료!", color=0xE74C3C) # 마감 느낌의 강렬한 레드
        embed.description = f"**이적 시장 기간이 공식적으로 종료되었습니다.**\n더 이상 `/팀가입` 명령어를 사용할 수 없습니다.\n\n{result_text}"
        embed.set_footer(text="참가자들은 각 팀의 음성 채널로 모여주시기 바랍니다.")
        
        await interaction.followup.send(embed=embed)

    except discord.Forbidden:
        await interaction.followup.send("❌ 봇에게 권한이 없습니다! 서버 설정에서 봇의 역할(Role) 위치를 유저들보다 위로 올리고, '역할 관리' 권한을 주세요.")
    except Exception as e:
        await interaction.followup.send(f"❌ 오류 발생: {str(e)}")

# ==========================================
# 🗓️ /대진표생성 슬래시 명령어 (관리자 전용)
# ==========================================
@bot.tree.command(name="대진표생성", description="[관리자 전용] 5개 팀의 풀리그(라운드 로빈) 10경기 대진표를 자동 생성합니다.")
@app_commands.default_permissions(administrator=True)
async def create_bracket_slash(interaction: discord.Interaction):
    
    # 봇이 처리하는 동안 대기 상태로 만들기 (안전장치 추가)
    try:
        await interaction.response.defer()
    except Exception:
        return

    @sync_to_async
    def generate_round_robin():
        try:
            teams = list(Team.objects.all())
            
            if len(teams) != 5:
                return False, f"❌ 현재 등록된 팀이 {len(teams)}개입니다. 2경기 동시 진행 알고리즘은 정확히 5팀일 때 작동합니다."

            # 기존 대진표가 있다면 초기화
            if Match.objects.exists():
                Match.objects.all().delete()
                for t in teams:
                    t.wins = 0
                    t.losses = 0
                    t.save()

            # 서클 알고리즘 (5팀 기준 완벽 분배)
            import random
            random.shuffle(teams)
            
            # [휴식, 팀1, 팀2, 팀3, 팀4, 팀5]
            teams_with_bye = [None] + teams
            new_matches = []
            match_number = 1

            # 총 5개의 라운드(타임 슬롯) 진행
            for round_num in range(5):
                round_matches = []
                
                # 양 끝에서부터 안쪽으로 짝을 지어줌
                for i in range(3):
                    team1 = teams_with_bye[i]
                    team2 = teams_with_bye[5 - i]
                    
                    # None(휴식)과 짝지어진 팀은 이번 라운드 쉬는 팀이므로 제외
                    if team1 is not None and team2 is not None:
                        round_matches.append((team1, team2))
                
                # 라운드 내에서 1, 2경기 순서도 섞어줌
                random.shuffle(round_matches)
                
                # 생성된 2경기를 DB 저장 리스트에 추가
                for t1, t2 in round_matches:
                    new_matches.append(Match(
                        match_number=match_number,
                        team_a=t1,
                        team_b=t2,
                        status='PENDING'
                    ))
                    match_number += 1
                
                # 서클 회전: 한 칸씩 밀어냄
                teams_with_bye = [None, teams_with_bye[5], teams_with_bye[1], teams_with_bye[2], teams_with_bye[3], teams_with_bye[4]]
            
            # DB에 한 번에 10경기 저장
            Match.objects.bulk_create(new_matches)
            
            return True, "✅ 5팀 완벽 분배 완료! 겹치는 팀 없이 **총 5라운드, 10경기** 대진표가 생성되었습니다."

        except Exception as e:
            return False, f"❌ 대진표 생성 중 데이터베이스 오류가 발생했습니다: {str(e)}"

    # 비동기로 로직 실행 및 결과 전송
    try:
        success, message = await generate_round_robin()
        
        if success:
            embed = discord.Embed(title="🗓️ TÆKTUBE 라운드 로빈 대진표 생성 완료!", color=0xF1C40F)
            embed.description = message + "\n\n웹사이트의 **Match Hub**를 새로고침해서 전체 대진표와 일정을 확인하세요!"
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(message)
            
    except Exception:
        await interaction.followup.send("❌ 디스코드 통신 중 오류가 발생했습니다. 다시 시도해 주세요.")

if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv('DISCORD_TOKEN'))