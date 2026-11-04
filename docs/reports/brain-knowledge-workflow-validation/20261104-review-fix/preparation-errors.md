판정 시작 준비 스크립트를 시스템 python3로 실행해 numpy import가 실패했다. 이때 run-judge.py는 생성되지 않아 두 hc 프로세스도 모델 호출 없이 종료했다. 워크트리 .venv/bin/python으로 준비를 완료한 뒤 별도 프로세스로 판정을 시작했다. 기능 실패·통과 세션으로 집계하지 않는다.
후속 시작에서는 hyphen 파일명 run-round.py를 run_round로 import하려다 두 프로세스가 모델 호출 없이 종료했다. importlib로 실제 파일을 읽도록 고쳤다. 두 준비 실패 모두 판정 결과에 포함하지 않는다.
