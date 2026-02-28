from django.db import models

class Team(models.Model):
    # 팀명은 나중에 유저가 바꿀 수 있도록 넉넉하게 설정
    name = models.CharField(max_length=50, unique=True, verbose_name="팀명")
    wins = models.IntegerField(default=0, verbose_name="승리")
    losses = models.IntegerField(default=0, verbose_name="패배")

    def __str__(self):
        return f"{self.name} ({self.wins}W {self.losses}L)"


class Player(models.Model):
    TIER_CHOICES = [(i, f'{i}티어') for i in range(1, 6)]
    
    POSITION_CHOICES = [
        ('TOP', '탑'),
        ('JUG', '정글'),
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
        """라이엇 ID(Name#Tag)를 OP.GG URL 포맷(Name-Tag)으로 변환"""
        if self.riot_id:
            # '#' 기호를 URL에 맞는 '-' 기호로 변경
            formatted_id = self.riot_id.replace('#', '-')
            # 북미 서버 기준 링크 (한국 서버면 'na'를 'kr'로 변경)
            return f"https://www.op.gg/summoners/na/{formatted_id}"
        return "#"


class Match(models.Model):
    STATUS_CHOICES = [
        ('PENDING', '대기 중'),
        ('IN_PROGRESS', '진행 중'),
        ('COMPLETED', '종료됨'),
    ]

    match_number = models.IntegerField(unique=True, verbose_name="경기 번호")
    team_a = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='matches_as_a', verbose_name="팀 A")
    team_b = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='matches_as_b', verbose_name="팀 B")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="상태")
    winner = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='won_matches', verbose_name="승리 팀")
    
    # 🌟 새롭게 추가된 기획: 타이브레이커(동률) 처리를 위한 게임 소요 시간
    # 봇이 "30:15" 형태로 입력하기 쉽게 문자열로 받고, 나중에 로직으로 계산할 수 있음
    game_duration = models.CharField(max_length=10, null=True, blank=True, verbose_name="게임 소요 시간 (MM:SS)")

    def __str__(self):
        return f"Game {self.match_number}: {self.team_a.name} vs {self.team_b.name}"