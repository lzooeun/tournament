from django.db import models

class Team(models.Model):
    GROUP_CHOICES = [
        ('A', 'Group A'),
        ('B', 'Group B'),
    ]
    name = models.CharField(max_length=50, unique=True, verbose_name="팀명")
    group = models.CharField(max_length=1, choices=GROUP_CHOICES, null=True, blank=True, verbose_name="소속 그룹")
    wins = models.IntegerField(default=0, verbose_name="승리")
    losses = models.IntegerField(default=0, verbose_name="패배")
    leader_discord_id = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        group_label = f"[{self.group}] " if self.group else ""
        return f"{group_label}{self.name} ({self.wins}W {self.losses}L)"


class Player(models.Model):
    TIER_CHOICES = [(i, f'{i}티어') for i in range(1, 6)]
    
    POSITION_CHOICES = [
        ('TOP', '탑'),
        ('JGL', '정글'),
        ('MID', '미드'),
        ('ADC', '원딜'),
        ('SUP', '서포터'),
        ('FILL', '상관없음'),
    ]

    # 기본 정보
    riot_id = models.CharField(max_length=100, verbose_name="라이엇 ID")
    discord_username = models.CharField(max_length=50, null=True, blank=True, verbose_name="디스코드 닉네임")
    discord_user_id = models.CharField(max_length=50, unique=True, verbose_name="디스코드 유저 ID(숫자)")
    
    # 대회 배정 티어 (1~5)
    tier = models.IntegerField(choices=TIER_CHOICES, verbose_name="대회 티어")
    
    # 포지션 및 솔랭 티어
    main_position = models.CharField(max_length=4, choices=POSITION_CHOICES, default='FILL', verbose_name="주 포지션")
    sub_position = models.CharField(max_length=4, choices=POSITION_CHOICES, verbose_name="부 포지션", null=True, blank=True)
    note = models.CharField(max_length=100, null=True, blank=True, verbose_name="특이사항/노트")
    highest_rank = models.CharField(max_length=50, null=True, blank=True, verbose_name="최고 티어 (예: Diamond 4)")
    solo_rank = models.CharField(max_length=50, null=True, blank=True, verbose_name="현재 티어 (예: Emerald 2)")
    
    # 소속 팀 (탕치기 기간에는 null일 수 있음)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='players', verbose_name="소속 팀")

    def __str__(self):
        return f"{self.riot_id} ({self.tier}T / {self.main_position})"
    
    @property
    def opgg_url(self):
        if self.riot_id:
            formatted_id = self.riot_id.replace('#', '-')
            return f"https://www.op.gg/summoners/na/{formatted_id}"
        return "#"


class Match(models.Model):
    STATUS_CHOICES = [
        ('PENDING', '대기 중'),
        ('IN_PROGRESS', '진행 중'),
        ('COMPLETED', '종료됨'),
    ]

    STAGE_CHOICES = [
        ('GROUP', '조별 리그 (Group Stage)'),
        ('DEATHMATCH', '데스매치 (Quarter Finals)'),
        ('SEMI', '세미 파이널 (Semi Finals)'),
        ('FINAL', '결승전 (Finals)'),
    ]

    match_number = models.IntegerField(unique=True, verbose_name="경기 번호")
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='GROUP', verbose_name="경기 스테이지")
    team_a = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='matches_as_a', verbose_name="팀 A")
    team_b = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='matches_as_b', verbose_name="팀 B")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="상태")
    winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='won_matches', verbose_name="승리 팀")
    game_duration = models.CharField(max_length=10, null=True, blank=True, verbose_name="게임 소요 시간 (MM:SS)")
    scheduled_time = models.CharField(max_length=20, null=True, blank=True, verbose_name="예정 시간")
    team_a_score = models.IntegerField(default=0, verbose_name="팀 A 스코어")
    team_b_score = models.IntegerField(default=0, verbose_name="팀 B 스코어")
    is_completed = models.BooleanField(default=False)
    screenshot_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"[{self.get_stage_display()}] Game {self.match_number}: {self.team_a.name} vs {self.team_b.name}"