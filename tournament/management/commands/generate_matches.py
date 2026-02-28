from django.core.management.base import BaseCommand
from tournament.models import Team, Match

class Command(BaseCommand):
    help = '5팀 풀리그(10경기) 대진표를 자동으로 생성합니다.'

    def handle(self, *args, **options):
        # 1. DB에 등록된 모든 팀 가져오기
        teams = list(Team.objects.all())

        # 5팀이 아니면 경고 메시지 띄우고 종료
        if len(teams) != 5:
            self.stdout.write(self.style.ERROR(f'현재 등록된 팀이 {len(teams)}개입니다. 5개의 팀을 먼저 관리자 페이지에서 만들어주세요!'))
            return

        # 2. 기존 경기가 있다면 깔끔하게 초기화(삭제)
        Match.objects.all().delete()
        self.stdout.write(self.style.WARNING('기존 경기 데이터를 모두 초기화했습니다.'))

        # 3. 체력 안배를 고려한 5팀 대진표 순서 (인덱스 기준: 0~4)
        # 1팀이 연속으로 2번 뛰는 일을 최대한 방지하는 알고리즘 순서야.
        match_order_indices = [
            (0, 1), # 1경기: 팀A vs 팀B
            (2, 3), # 2경기: 팀C vs 팀D
            (4, 0), # 3경기: 팀E vs 팀A
            (1, 2), # 4경기: 팀B vs 팀C
            (3, 4), # 5경기: 팀D vs 팀E
            (0, 2), # 6경기: 팀A vs 팀C
            (1, 3), # 7경기: 팀B vs 팀D
            (2, 4), # 8경기: 팀C vs 팀E
            (3, 0), # 9경기: 팀D vs 팀A
            (4, 1), # 10경기: 팀E vs 팀B
        ]

        # 4. 10경기 객체 생성 후 DB에 한 번에 저장 (bulk_create)
        matches_to_create = []
        for i, (idx_a, idx_b) in enumerate(match_order_indices, start=1):
            team_a = teams[idx_a]
            team_b = teams[idx_b]
            
            matches_to_create.append(
                Match(match_number=i, team_a=team_a, team_b=team_b, status='PENDING')
            )

        Match.objects.bulk_create(matches_to_create)

        self.stdout.write(self.style.SUCCESS('🎉 성공적으로 10경기의 대진표가 쫙 생성되었습니다! 웹사이트를 새로고침 해보세요.'))