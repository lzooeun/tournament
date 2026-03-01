from django.shortcuts import render
from collections import defaultdict
from django.db.models import Q
from .models import Player, Team, Match

def get_standings():
    # 1. 모든 팀의 기본 통계 구조(Dictionary) 생성
    stats = {}
    for team in Team.objects.all():
        stats[team.id] = {
            'team': team,
            'wins': 0,
            'losses': 0,
            'total_win_seconds': 0,
            'avg_win_seconds': float('inf'), 
            'avg_win_time_str': "-",
            'h2h_wins': [] 
        }

    # 2. 종료된 매치 데이터를 바탕으로 승패 및 시간 계산
    # 🚨 주의: 네 기존 코드에 있던 status='COMPLETED' 대신, 
    # 봇 코드와 통일하기 위해 is_completed=True 로 변경했어! (모델 필드 확인 필수)
    completed_matches = Match.objects.filter(is_completed=True)
    
    for match in completed_matches:
        if match.winner:
            loser = match.team_b if match.team_a == match.winner else match.team_a
            
            # 승패 기록 및 승자승(H2H) 데이터 추가
            stats[match.winner.id]['wins'] += 1
            stats[loser.id]['losses'] += 1
            stats[match.winner.id]['h2h_wins'].append(loser.id)

            # 승리 시간 초(Seconds) 단위로 변환
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
    
    for i in range(5):
        if i < len(db_teams):
            team = db_teams[i]
            players = list(team.players.all())
            padded_players = players + [None] * (5 - len(players))
            teams_data.append({
                'name': team.name, 
                'players': padded_players
            })
        else:
            teams_data.append({
                'name': f'Team {chr(65+i)} (미정)', 
                'players': [None] * 5
            })

    # 3. Match Hub 좌측 경기 목록용 데이터
    matches = Match.objects.all().order_by('match_number')
    
    # 4. Match Hub 우측 랭킹 테이블용 데이터 (여기서 호출!)
    current_standings = get_standings()

    # 5. 모든 데이터를 컨텍스트에 담아서 HTML로 발사
    return render(request, 'tournament/home.html', {
        'players_by_tier': players_by_tier,
        'teams': teams_data,
        'matches': matches,
        'standings': current_standings, # 🎯 HTML의 {% for row in standings %}와 연결됨!
    })