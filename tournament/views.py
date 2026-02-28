from django.shortcuts import render
from django.db.models import Q
from .models import Player, Team, Match

def home(request):
    players_by_tier = {i: Player.objects.filter(tier=i) for i in range(1, 6)}
    
    # ✨ 팀이 5개가 안 되더라도 항상 5개를 보여주기 위한 기본 세팅
    # DB에 팀이 없으면 여기서 빈 구조라도 만들어서 넘겨줌
    db_teams = list(Team.objects.prefetch_related('players').all())
    
    teams_data = []
    for i in range(5):
        if i < len(db_teams):
            team = db_teams[i]
            # 승패 동적 계산 (관리자 페이지에서 변경해도 자동으로 순위표에 반영됨!)
            wins = Match.objects.filter(winner=team).count()
            losses = Match.objects.filter(Q(team_a=team) | Q(team_b=team), status='COMPLETED').exclude(winner=team).count()
            
            # 5명 슬롯 맞추기 (빈자리는 None으로 채움)
            players = list(team.players.all())
            padded_players = players + [None] * (5 - len(players))
            
            teams_data.append({
                'name': team.name, 'wins': wins, 'losses': losses, 'players': padded_players
            })
        else:
            # DB에 아직 팀이 5개가 안 만들어졌을 때 보여줄 가짜(Placeholder) 팀
            teams_data.append({
                'name': f'Team {chr(65+i)} (미정)', 'wins': 0, 'losses': 0, 'players': [None] * 5
            })

    matches = Match.objects.all().order_by('match_number')
    
    # 승리 순으로 내림차순, 패배 순으로 오름차순 정렬
    rankings = sorted(teams_data, key=lambda t: (-t['wins'], t['losses']))

    return render(request, 'tournament/home.html', {
        'players_by_tier': players_by_tier,
        'teams': teams_data,
        'matches': matches,
        'rankings': rankings,
    })