from django.shortcuts import render
from collections import defaultdict
from django.db.models import Q
from django.http import HttpResponse
from .models import Player, Team, Match

def get_standings(group_name):
    # 1. 모든 팀의 기본 통계 구조(Dictionary) 생성
    stats = {}
    teams_in_group = Team.objects.filter(group=group_name)
    for team in teams_in_group:
        stats[team.id] = {
            'team': team,
            'wins': 0,
            'losses': 0,
            'total_win_seconds': 0,
            'avg_win_seconds': float('inf'), 
            'avg_win_time_str': "-",
            'h2h_wins': [] 
        }

    # 2. '조별 리그(GROUP)' 단계이면서 종료된 경기만 필터링
    completed_group_matches = Match.objects.filter(is_completed=True, stage='GROUP')
    
    for match in completed_group_matches:
        # 이 경기가 현재 계산하려는 조의 경기인지 확인 (팀 A의 소속 조를 확인)
        if match.team_a.group == group_name and match.winner:
            loser = match.team_b if match.team_a == match.winner else match.team_a
            
            stats[match.winner.id]['wins'] += 1
            stats[loser.id]['losses'] += 1
            stats[match.winner.id]['h2h_wins'].append(loser.id)

            if match.game_duration:
                try:
                    minutes, seconds = map(int, match.game_duration.split(':'))
                    stats[match.winner.id]['total_win_seconds'] += (minutes * 60 + seconds)
                except ValueError:
                    pass

    # 3. 평균 승리 시간 계산 및 포맷팅
    for t_id, data in stats.items():
        if data['wins'] > 0:
            avg_sec = data['total_win_seconds'] / data['wins']
            data['avg_win_seconds'] = avg_sec
            
            m = int(avg_sec // 60)
            s = int(avg_sec % 60)
            data['avg_win_time_str'] = f"{m:02d}:{s:02d}"

    # ==========================================
    # [ TIE-BREAKER LOGIC ] 순위 정렬 알고리즘
    # ==========================================
    win_groups = defaultdict(list)
    for data in stats.values():
        win_groups[data['wins']].append(data)

    final_ranking = []
    
    for wins in sorted(win_groups.keys(), reverse=True):
        group = win_groups[wins]
        
        if len(group) == 1:
            final_ranking.extend(group)
            
        elif len(group) == 2:
            t1, t2 = group[0], group[1]
            if t2['team'].id in t1['h2h_wins']:
                final_ranking.extend([t1, t2])
            elif t1['team'].id in t2['h2h_wins']:
                final_ranking.extend([t2, t1])
            else:
                group.sort(key=lambda x: x['avg_win_seconds'])
                final_ranking.extend(group)
                
        else:
            group.sort(key=lambda x: x['avg_win_seconds'])
            final_ranking.extend(group)

    # 최종 순위 번호 부여
    for idx, data in enumerate(final_ranking):
        data['rank'] = idx + 1

    return final_ranking


# ==========================================
# 메인 렌더링 뷰 (URL과 연결되는 함수)
# ==========================================
def home(request):
    # 1. 하단 Player List 용 데이터
    players_by_tier = {i: Player.objects.filter(tier=i) for i in range(1, 6)}
    
    # 2. 상단 Team List 용 데이터 (빈 자리 Placeholder 포함)
    db_teams = list(Team.objects.prefetch_related('players').all())
    teams_data = []
    
    for i in range(6):
        if i < len(db_teams):
            team = db_teams[i]
            players = list(team.players.all())
            padded_players = players + [None] * (5 - len(players))
            teams_data.append({
                'name': team.name, 
                'group': team.group,
                'players': padded_players
            })
        else:
            teams_data.append({
                'name': f'Team {chr(65+i)} (미정)', 
                'group': None,
                'players': [None] * 5
            })

    # 3. Match Hub 좌측 경기 목록용 데이터
    matches = Match.objects.all().order_by('match_number')
    
    # 4. Match Hub 우측 랭킹 테이블용 데이터
    group_a_standings = get_standings('A')
    group_b_standings = get_standings('B')

    # 5. 모든 데이터를 컨텍스트에 담아서 HTML로 발사
    return render(request, 'tournament/home.html', {
        'players_by_tier': players_by_tier,
        'teams': teams_data,
        'matches': matches,
        'group_a_standings': group_a_standings,
        'group_b_standings': group_b_standings,
    })

def server_ping(request):
    return HttpResponse("OK")