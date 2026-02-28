from django.contrib import admin
from .models import Team, Player, Match

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    # discord_role_id는 빼고 깔끔하게 이름, 승, 패만 보여주기
    list_display = ('name', 'wins', 'losses')

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    # 새로 추가한 포지션과 솔랭 티어까지 한눈에 보이게 설정!
    list_display = ('riot_id', 'discord_username', 'tier', 'main_position', 'sub_position', 'solo_rank', 'team')
    list_filter = ('tier', 'team', 'main_position') # 포지션별로 필터링하는 기능도 추가

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    # 타이브레이커용 소요 시간(game_duration) 추가
    list_display = ('match_number', 'team_a', 'team_b', 'winner', 'status', 'game_duration')
    list_filter = ('status',)