import os
import sys
from pathlib import Path
from typing import List

# Windows 콘솔 UTF-8 인코딩 설정 (이모지 및 한글 깨짐/cp949 오류 방지)
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 모듈 경로 추가
if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).parent))

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.markup import escape
    USE_RICH = True
    console = Console()
except ImportError:
    USE_RICH = False
    console = None
    escape = lambda s: s

from src.config import ConfigManager
from src.scanner import ModScanner
from src.backup import BackupManager
from src.updater import ModUpdater

def print_banner():
    title = "🎮 심즈 4 모드 자동 업데이터 (Sims 4 Mod Auto Updater) v0.1.1"
    if USE_RICH:
        console.print(Panel(f"[bold cyan]{title}[/bold cyan]\n[dim]EA The Sims 4 Mod Management Tool[/dim]"))
    else:
        print("=" * 60)
        print(title)
        print("=" * 60)

def handle_subfolder_search(scanner: ModScanner, target_dirs: List[Path], selected_mod: dict) -> str:
    """하위 폴더 파일 목록을 출력하고, 파일을 하나 선택한 뒤 작업 메뉴(1. 다른 메뉴 전환, 2. 하위 폴더 검색하기, 3. 웹 검색, 4. 종료)를 수행합니다.
    반환값:
        'menu': 다른 메뉴로 전환
        'exit': 프로그램 종료
        'web_search': 웹에서 최신 버전/배포 페이지 검색
        'back': 이전 화면으로 복귀
    """
    while True:
        all_collected_files = []
        for t_dir in target_dirs:
            file_res = scanner.scan_all_mod_files(t_dir)
            all_files = file_res["all_files"]
            pkgs = file_res["packages"]
            scrs = file_res["scripts"]
            warnings = file_res.get("warnings", [])

            if USE_RICH:
                console.print(f"\n[bold cyan]📂 [{t_dir.name}] 내 전체 모드 파일 목록 (총 {len(all_files)}개: .package {len(pkgs)}개, .ts4script {len(scrs)}개):[/bold cyan]")
                console.print(f"[dim]위치: {t_dir}[/dim]\n")

                if not all_files:
                    console.print("[dim]포함된 .package 또는 .ts4script 파일이 없습니다.[/dim]")
                else:
                    table = Table(show_lines=False)
                    table.add_column("번호", justify="right", style="cyan", width=5)
                    table.add_column("종류", style="bold", width=12)
                    table.add_column("파일명", style="white")
                    table.add_column("폴더 위치", style="dim green")

                    for idx, f in enumerate(all_files, 1):
                        type_styled = "[green].ts4script[/green]" if f["type"] == ".ts4script" else "[magenta].package[/magenta]"
                        loc_styled = "[dim](루트)[/dim]" if f["location"] == "." else f["location"]
                        table.add_row(str(idx), type_styled, f["name"], loc_styled)
                    console.print(table)

                if warnings:
                    console.print("\n[bold yellow]⚠️ 스크립트 모드 깊이 주의 사항:[/bold yellow]")
                    for w in warnings:
                        console.print(f"  • [yellow]{w}[/yellow]")
            else:
                print(f"\n📂 [{t_dir.name}] 내 전체 모드 파일 목록 (총 {len(all_files)}개: .package {len(pkgs)}개, .ts4script {len(scrs)}개):")
                print(f"위치: {t_dir}\n")

                if not all_files:
                    print("포함된 .package 또는 .ts4script 파일이 없습니다.")
                else:
                    print(f"{'번호':>4} | {'종류':<11} | {'파일명':<45} | 폴더 위치")
                    print("-" * 80)
                    for idx, f in enumerate(all_files, 1):
                        loc_str = "(루트)" if f["location"] == "." else f["location"]
                        print(f"{idx:>4} | {f['type']:<11} | {f['name']:<45} | {loc_str}")

                if warnings:
                    print("\n⚠️ 스크립트 모드 깊이 주의 사항:")
                    for w in warnings:
                        print(f"  • {w}")

            all_collected_files.extend(all_files)

        if not all_collected_files:
            input("\n돌아가려면 Enter 키를 누르세요...")
            return "back"

        # 파일 선택 안내
        print("\n확인할 파일 번호를 선택하세요 (b: 이전 화면으로 돌아가기)")
        f_choice = input("파일 선택 > ").strip().lower()

        if f_choice in ["b", "back"]:
            return "back"
        if f_choice in ["q", "exit"]:
            return "exit"

        if not f_choice.isdigit() or not (1 <= int(f_choice) <= len(all_collected_files)):
            print("\n[!] 올바른 파일 번호를 입력해 주세요.")
            continue

        selected_file = all_collected_files[int(f_choice) - 1]
        selected_mod["selected_file"] = selected_file
        selected_mod["name"] = selected_file["name"]
        selected_mod["file_path"] = selected_file["full_path"]

        # 파일 내부 바이너리/아카이브 메타데이터(.package / .ts4script) 즉시 추출
        from src.finder import extract_mod_file_metadata
        file_meta = extract_mod_file_metadata(selected_file["full_path"])

        meta_rich_lines = []
        meta_plain_lines = []
        if file_meta.get("inferred_creator"):
            meta_rich_lines.append(f"[bold]👤 내장 제작자(Creator):[/bold] [cyan]{escape(file_meta['inferred_creator'])}[/cyan]")
            meta_plain_lines.append(f"- 내장 제작자(Creator): {file_meta['inferred_creator']}")
        if file_meta.get("manifest_name") or file_meta.get("inferred_mod"):
            mod_label = file_meta.get("manifest_name") or file_meta.get("inferred_mod")
            meta_rich_lines.append(f"[bold]📌 내부 식별 모드명:[/bold] {escape(mod_label)}")
            meta_plain_lines.append(f"- 내부 식별 모드명: {mod_label}")
        if file_meta.get("version"):
            meta_rich_lines.append(f"[bold]🔖 내장 버전:[/bold] [green]v{escape(file_meta['version'])}[/green]")
            meta_plain_lines.append(f"- 내장 버전: v{file_meta['version']}")

        meta_rich_block = ("\n" + "\n".join(meta_rich_lines)) if meta_rich_lines else ""

        # 선택된 파일 정보 표시
        if USE_RICH:
            file_display = escape(f"[{selected_file['name']}]")
            console.print(Panel(
                f"[bold green]선택된 파일은 {file_display}입니다.[/bold green]\n\n"
                f"[bold]📁 파일 경로:[/bold] {selected_file['full_path']}\n"
                f"[bold]🏷️ 파일 종류:[/bold] {selected_file['type']}\n"
                f"[bold]📂 폴더 위치:[/bold] {selected_file['location']}"
                f"{meta_rich_block}",
                title=f"[bold cyan]{escape(selected_file['name'])} 파일 및 내부 메타데이터 정보[/bold cyan]",
                border_style="cyan"
            ))
        else:
            print("\n" + "=" * 60)
            print(f"선택된 파일은 [{selected_file['name']}]입니다.")
            print(f"- 파일 경로: {selected_file['full_path']}")
            print(f"- 파일 종류: {selected_file['type']}")
            print(f"- 폴더 위치: {selected_file['location']}")
            for line in meta_plain_lines:
                print(line)
            print("=" * 60)

        # 사용자 요청 작업 메뉴 표시:
        # [원하시는 작업을 선택하세요]
        # 1. 다른 메뉴로 전환
        # 2. 하위 폴더 검색하기
        # 3. 웹에서 최신 버전/배포 페이지 검색
        # 4. 프로그램 종료
        while True:
            print("\n[원하시는 작업을 선택하세요]")
            print("1. 다른 메뉴로 전환")
            print("2. 하위 폴더 검색하기")
            print("3. 웹에서 최신 버전/배포 페이지 검색")
            print("4. 프로그램 종료")

            act_choice = input("\n선택 (1/2/3/4) > ").strip()

            if act_choice == "1":
                print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
                return "menu"
            elif act_choice == "2":
                # 다시 하위 폴더 파일 목록으로 이동
                break
            elif act_choice == "3":
                selected_mod["name"] = selected_file["name"]
                return "web_search"
            elif act_choice in ["4", "q", "exit"]:
                return "exit"
            else:
                print("\n[!] 1, 2, 3, 4 번호 중 하나를 입력해 주세요.")

def handle_mod_installed_check(scanner: ModScanner, mod: dict) -> str:
    """선택한 모드의 package와 ts4script 파일이 Mods 폴더에 이미 감지될 경우 또는 없을 경우 선택지를 안내합니다.
    반환값:
        'web_search_installed': 설치 감지 상태에서 웹 최신 버전/배포 페이지 검색
        'web_search_new': 미설치 상태에서 웹 최신 버전/배포 페이지 검색
        'menu': 다른 메뉴로 전환 (메인 메뉴로 이동)
        'exit': 프로그램 종료
    """
    mod_name = mod.get("name", "선택한 모드")
    folder_name = mod.get("folder_name") or mod.get("install_folder") or mod_name
    info = scanner.detect_mod_installed(mod)

    # 감지된 package 또는 ts4script 파일 이름 및 경로 결정 (폴더 이름 대신 모드 이름으로 사용)
    detected_file_name = None
    detected_file_path = None
    if "selected_file" in mod:
        detected_file_name = mod["selected_file"]["name"]
        detected_file_path = mod["selected_file"].get("full_path")
    elif info.get("scripts"):
        chosen_scr = next(
            (p for p in info["scripts"] if "cmd_center" in p.name.lower() or "scripts" in p.name.lower() or "main" in p.name.lower()),
            info["scripts"][0]
        )
        detected_file_name = chosen_scr.name
        detected_file_path = str(chosen_scr)
    elif info.get("packages"):
        chosen_pkg = next(
            (p for p in info["packages"] if "!wamtik" in p.name.lower() or "_wamtik" in p.name.lower()),
            info["packages"][0]
        )
        detected_file_name = chosen_pkg.name
        detected_file_path = str(chosen_pkg)

    if detected_file_name:
        mod["name"] = detected_file_name
    if detected_file_path:
        mod["file_path"] = detected_file_path

    # 1. 대상 모드가 감지되었을 때
    if info["installed"]:
        loc_text = "\n".join([f"  • {loc}" for loc in info["locations"]])
        duplicates = info.get("duplicates", [])

        # package / ts4script 중복 감지 섹션
        dup_section_rich = ""
        dup_section_plain = ""
        if duplicates:
            dup_rich_lines = ["[bold red]⚠️ 중복된 모드 파일 감지 (.package / .ts4script):[/bold red]"]
            dup_plain_lines = ["\n⚠️ 중복된 모드 파일 감지 (.package / .ts4script):"]
            for dup in duplicates:
                dup_rich_lines.append(f"  • [red]{dup['file_name']}[/red]\n    - 기존: [dim]{dup['original_path']}[/dim]\n    - 중복: [bold red]{dup['duplicate_path']}[/bold red]")
                dup_plain_lines.append(f"  • {dup['file_name']}\n    - 기존: {dup['original_path']}\n    - 중복: {dup['duplicate_path']}")
            dup_section_rich = "\n\n" + "\n".join(dup_rich_lines)
            dup_section_plain = "\n" + "\n".join(dup_plain_lines)
        else:
            dup_section_rich = "\n\n[dim green]✅ 중복된 .package / .ts4script 파일 없음 (정상)[/dim green]"
            dup_section_plain = "\n- 중복 파일 검사: 중복된 파일 없음 (정상)"

        if USE_RICH:
            panel_title = f"[bold red]{escape(folder_name)} (⚠️ 중복 파일 감지)[/bold red]" if duplicates else f"[bold cyan]{escape(folder_name)} 모드 정보[/bold cyan]"
            border_style = "red" if duplicates else "cyan"
            folder_display = escape(f"[{folder_name}]")

            console.print(Panel(
                f"[bold green]선택된 폴더는 {folder_display}입니다.[/bold green]\n\n"
                f"[bold]📁 감지된 위치:[/bold]\n{loc_text}\n\n"
                f"[bold]📦 감지된 .package 파일:[/bold] {len(info['packages'])}개\n"
                f"[bold]📜 감지된 .ts4script 파일:[/bold] {len(info['scripts'])}개"
                f"{dup_section_rich}",
                title=panel_title,
                border_style=border_style
            ))
        else:
            print("\n" + "=" * 60)
            print(f"선택된 폴더는 [{folder_name}]입니다.")
            print(f"- 감지된 위치: {', '.join(info['locations'])}")
            print(f"- 감지된 .package 파일: {len(info['packages'])}개")
            print(f"- 감지된 .ts4script 파일: {len(info['scripts'])}개")
            if dup_section_plain:
                print(dup_section_plain.strip())
            print("=" * 60)

        while True:
            print("\n[원하시는 작업을 선택하세요]")
            print("1. 다른 메뉴로 전환")
            print("2. 하위 폴더 검색하기")
            print("3. 프로그램 종료")

            choice = input("\n선택 (1/2/3) > ").strip()

            if choice == "1":
                print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
                return "menu"
            elif choice == "2":
                # 하위 폴더 검색하기: 폴더 및 모든 하위 폴더 내 전체 .package 및 .ts4script 파일 목록 출력 및 파일 선택
                target_dirs = info.get("target_dirs", [])
                if not target_dirs:
                    print("\n[!] 대상 모드 폴더를 찾을 수 없습니다.")
                    continue

                sub_action = handle_subfolder_search(scanner, target_dirs, selected_mod=mod)
                if sub_action == "exit":
                    return "exit"
                elif sub_action == "menu":
                    return "menu"
                elif sub_action == "web_search":
                    return "web_search_installed"
                elif sub_action == "back":
                    continue
            elif choice in ["3", "q", "exit"]:
                return "exit"
            else:
                print("\n[!] 1, 2, 3 번호 중 하나를 입력해 주세요.")
    else:
        # 2. package 또는 ts4script가 감지되지 않았을 때 (미설치 상태)
        keywords_str = ", ".join(mod.get("folder_keywords", [mod_name]))
        f_kw = mod.get("file_keywords", [])
        f_kw_str = f"\n• 파일 키워드: [dim]{', '.join(f_kw)}[/dim]" if f_kw else ""
        f_kw_plain = f"\n- 파일 키워드: {', '.join(f_kw)}" if f_kw else ""

        if USE_RICH:
            console.print(Panel(
                f"[bold cyan]ℹ️ Mods 폴더에 [{mod_name}] 모드가 감지되지 않았습니다.[/bold cyan]\n\n"
                f"• 폴더 키워드: [dim]{keywords_str}[/dim]{f_kw_str}\n"
                f"• 대상 경로: [dim]{scanner.mods_folder}[/dim]",
                title=f"[bold cyan]{mod_name} 미설치 확인[/bold cyan]",
                border_style="cyan"
            ))
        else:
            print("\n" + "=" * 60)
            print(f"ℹ️ Mods 폴더에 [{mod_name}] 모드가 감지되지 않았습니다.")
            print(f"- 폴더 키워드: {keywords_str}{f_kw_plain}")
            print("=" * 60)

        while True:
            print("\n[원하시는 작업을 선택하세요]")
            print("1. 다시 검색 (웹에서 최신 버전/배포 페이지 검색)")
            print("2. 다른 메뉴로 전환")
            print("3. 프로그램 종료")

            choice = input("\n선택 (1/2/3) > ").strip()

            if choice == "1":
                return "web_search_new"
            elif choice == "2":
                print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
                return "menu"
            elif choice in ["3", "q", "exit"]:
                return "exit"
            else:
                print("\n[!] 1, 2, 3 번호 중 하나를 입력해 주세요.")

def show_status(config_mgr: ConfigManager):
    mods_folder = config_mgr.mods_folder
    scanner = ModScanner(mods_folder)
    scan_res = scanner.scan()

    if USE_RICH:
        table = Table(title="📊 전체 모드 폴더 요약 통계")
        table.add_column("항목", style="cyan")
        table.add_column("내용", style="green")

        table.add_row("Mods 경로", str(mods_folder))
        table.add_row("폴더 존재 여부", "✅ 정상" if scan_res["exists"] else "❌ 찾을 수 없음")
        table.add_row(".package 파일 수", str(scan_res["package_count"]))
        table.add_row(".ts4script 파일 수", str(scan_res["script_count"]))
        table.add_row("총 모드 파일 수", str(scan_res["total_count"]))
        console.print(table)

        if scan_res["warnings"]:
            console.print("\n[bold yellow]⚠️ 감지된 경고 사항:[/bold yellow]")
            for w in scan_res["warnings"]:
                console.print(f"  - {w}")

        # 현재 사용자가 가지고 있는 모드 목록 (1단계 폴더 기준) 스캔 및 출력
        user_mods_res = scanner.scan_user_mods()
        folder_mods = user_mods_res["folder_mods"]
        standalone_files = user_mods_res["standalone_files"]

        if folder_mods:
            mod_table = Table(title=f"\n📦 현재 설치된 모드 폴더 목록 (총 {len(folder_mods)}개 감지됨)")
            mod_table.add_column("No", justify="center", style="dim", width=4)
            mod_table.add_column("모드 폴더명", style="bold cyan")
            mod_table.add_column("분류", justify="center")
            mod_table.add_column(".package (전체)", justify="right", style="magenta")
            mod_table.add_column(".ts4script (전체)", justify="right", style="green")
            mod_table.add_column("보조 하위폴더", justify="right", style="dim")

            for idx, f_mod in enumerate(folder_mods, 1):
                type_style = "[bold green]" if "스크립트" in f_mod["mod_type"] else "[cyan]"
                if "한글" in f_mod["mod_type"]:
                    type_style = "[bold yellow]"
                elif "CC" in f_mod["mod_type"]:
                    type_style = "[dim]"

                sub_text = f"{f_mod['subdir_count']}개" if f_mod['subdir_count'] > 0 else "-"
                mod_table.add_row(
                    str(idx),
                    f_mod["name"],
                    f"{type_style}{f_mod['mod_type']}[/]",
                    f"{f_mod['package_count']}개",
                    f"{f_mod['script_count']}개",
                    sub_text
                )
            console.print(mod_table)

        if standalone_files:
            file_names = [f["name"] for f in standalone_files]
            preview = ", ".join(file_names[:5]) + (f" 외 {len(file_names)-5}개" if len(file_names) > 5 else "")
            console.print(f"\n[dim]📄 Mods 루트 단일 파일: 총 {len(standalone_files)}개 ({preview})[/dim]")
    else:
        print("\n[전체 모드 폴더 요약 통계]")
        print(f"- Mods 경로: {mods_folder}")
        print(f"- 폴더 존재: {'정상' if scan_res['exists'] else '찾을 수 없음'}")
        print(f"- .package: {scan_res['package_count']}개")
        print(f"- .ts4script: {scan_res['script_count']}개")
        if scan_res["warnings"]:
            print("\n[경고]")
            for w in scan_res["warnings"]:
                print(f"  - {w}")

        user_mods_res = scanner.scan_user_mods()
        folder_mods = user_mods_res["folder_mods"]
        standalone_files = user_mods_res["standalone_files"]

        if folder_mods:
            print(f"\n[현재 설치된 모드 폴더 목록 (총 {len(folder_mods)}개)]")
            for idx, f_mod in enumerate(folder_mods, 1):
                print(f"  {idx}. {f_mod['name']} [{f_mod['mod_type']}] -> package: {f_mod['package_count']}개, script: {f_mod['script_count']}개 (하위폴더: {f_mod['subdir_count']}개)")

        if standalone_files:
            print(f"\n- Mods 루트 단일 파일: 총 {len(standalone_files)}개")

def check_updates(updater: ModUpdater):
    mods = updater.load_manifest()
    if not mods:
        print("\n[!] 등록된 모드가 없습니다. mods_manifest.json을 확인하세요.")
        return []

    print("\n🔍 모드 업데이트 확인 중...")
    results = []
    for mod in mods:
        res = updater.check_mod_update(mod)
        results.append((mod, res))

    if USE_RICH:
        table = Table(title="업데이트 확인 결과")
        table.add_column("모드 이름", style="cyan")
        table.add_column("현재 버전", style="magenta")
        table.add_column("최신 버전", style="green")
        table.add_column("업데이트 여부", style="bold")

        for mod, res in results:
            if "error" in res:
                table.add_row(mod["name"], mod.get("current_version", "-"), "오류", f"[red]{res['error']}[/red]")
            else:
                status = "[green]가능[/green]" if res["has_update"] else "[dim]최신 상태[/dim]"
                table.add_row(
                    mod["name"],
                    mod.get("current_version") or "(미설치)",
                    res["latest_version"],
                    status
                )
        console.print(table)
    else:
        print("\n[업데이트 확인 결과]")
        for mod, res in results:
            if "error" in res:
                print(f"- {mod['name']}: 오류 ({res['error']})")
            else:
                up_text = "업데이트 가능!" if res["has_update"] else "최신 상태"
                cur_ver = mod.get('current_version') or '(미설치)'
                print(f"- {mod['name']}: {cur_ver} -> {res['latest_version']} [{up_text}]")

    return results

def select_and_check_mod_update(updater: ModUpdater, scanner: ModScanner) -> bool:
    """1번 스캔 결과에서 스크립트 모드 분류에 해당하는 모드들을 자동으로 가져와 목록으로 표시하고,
    사용자가 번호로 선택하여 업데이트 및 중복 감지 작업을 진행하도록 합니다.
    반환값:
        True: 메인 메뉴 유지
        False: 프로그램 종료
    """
    # 1. Mods 폴더에서 현재 감지된 모드 스캔 자료 가져오기
    user_mods_res = scanner.scan_user_mods()
    folder_mods = user_mods_res.get("folder_mods", [])

    # 2. 스크립트 모드 분류에 해당하는 모드만 필터링 (ts4script가 있거나 한글화 모드)
    script_mods = [
        m for m in folder_mods
        if m.get("script_count", 0) > 0 or "스크립트" in m.get("mod_type", "") or "한글" in m.get("mod_type", "")
    ]

    if not script_mods:
        print("\n[!] Mods 폴더에서 스크립트 모드가 감지되지 않았습니다. 1번 메뉴에서 Mods 폴더 상태를 확인하세요.")
        return True

    while True:
        if USE_RICH:
            console.print(f"\n[bold cyan]📋 감지된 스크립트 모드 목록 (총 {len(script_mods)}개 감지됨, 업데이트할 모드를 선택하세요):[/bold cyan]")
            for idx, m in enumerate(script_mods, 1):
                script_info = f"[green]ts4script: {m['script_count']}개[/green]" if m['script_count'] > 0 else "[yellow]한글화 패키지[/yellow]"
                pkg_info = f"[magenta]package: {m['package_count']}개[/magenta]"
                console.print(f"  [bold green]{idx:2d}.[/bold green] [bold]{m['name']:<30}[/bold] [dim]({script_info}, {pkg_info})[/dim]")
            console.print("  [bold yellow] b.[/bold yellow] 메인 메뉴로 돌아가기")
        else:
            print(f"\n📋 감지된 스크립트 모드 목록 (총 {len(script_mods)}개, 업데이트할 모드를 선택하세요):")
            for idx, m in enumerate(script_mods, 1):
                print(f"  {idx:2d}. {m['name']:<30} (ts4script: {m['script_count']}개, package: {m['package_count']}개)")
            print("   b. 메인 메뉴로 돌아가기")

        choice = input("\n모드 선택 > ").strip().lower()

        if choice in ["b", "back"]:
            return True
        if choice in ["q", "exit"]:
            return False

        if not choice.isdigit() or not (1 <= int(choice) <= len(script_mods)):
            print("\n[!] 올바른 번호를 입력해 주세요.")
            continue

        selected_entry = script_mods[int(choice) - 1]
        folder_name = selected_entry["name"]
        # 선택한 폴더명을 기반으로 메타데이터 및 배포처 자동 추론
        selected_mod = updater.infer_mod_config(folder_name)
        selected_mod["folder_name"] = folder_name

        print(f"\n🔍 [{folder_name}] 설치 및 업데이트 상태 확인 중...")

        # 1. 경로에 동일한 모드가 이미 설치되어 있는지 package & ts4script 감지
        check_result = handle_mod_installed_check(scanner, selected_mod)
        if check_result == "exit":
            return False
        elif check_result == "menu":
            return True
        elif check_result in ["web_search_installed", "web_search_new"]:
            is_already_installed = (check_result == "web_search_installed")

            # 선택된 파일이 있거나 감지된 파일명이 있으면 모드 이름 및 실제 파일 경로를 확정
            if "selected_file" in selected_mod:
                f_name = selected_mod["selected_file"]["name"]
                selected_mod["name"] = f_name
                selected_mod["file_path"] = selected_mod["selected_file"].get("full_path")
                # 전용 스크래퍼(MCCC, WickedWhims 본체, 바람별 한글화 본체) 파일이 아닌 개별 모드/하위 패키지인 경우
                # 파일 내부 바이너리 메타데이터 추출 기반 배포처 검색(generic_web)으로 전환
                f_lower = f_name.lower()
                is_core_special_file = (
                    (selected_mod.get("source_type") == "mccc" and "mc_" in f_lower)
                    or (selected_mod.get("source_type") == "wickedwhims" and "turbodriver_wickedwhims" in f_lower)
                    or (selected_mod.get("source_type") == "barambyul" and "wamtik" in f_lower)
                )
                if not is_core_special_file:
                    selected_mod["source_type"] = "generic_web"
                    selected_mod["download_url"] = ""
                    selected_mod["homepage"] = ""
                    selected_mod["creator"] = "파일 내부 메타데이터 자동 감지"

            print(f"\n🌐 [{selected_mod['name']}] 파일 내부 메타데이터 분석 및 최신 배포 페이지 검색 중입니다...")
            res = updater.check_mod_update(selected_mod)

            if "error" in res:
                print(f"\n❌ 웹 검색 실패: {res['error']}")
            else:
                status_text = "✅ 이미 설치됨 (중복 감지 완료)" if is_already_installed else "ℹ️ 미설치"
                up_text = res.get("status_label") or ("🚀 최신 버전 배포 중" if res.get("has_update") else "수동 등록 필요")

                if USE_RICH:
                    table = Table(title=f"[{escape(selected_mod['name'])}] 웹 최신 릴리스 정보")
                    table.add_column("항목", style="cyan")
                    table.add_column("내용", style="green")
                    table.add_row("모드 이름", selected_mod["name"])
                    table.add_row("로컬 설치 상태", status_text)
                    table.add_row("웹 최신 버전", res.get("latest_version", "-"))
                    table.add_row("상태", up_text)
                    if res.get("release_notes"):
                        table.add_row("참고 사항", res.get("release_notes"))
                    console.print(table)
                else:
                    print(f"- 모드: {selected_mod['name']}")
                    print(f"- 로컬 설치 상태: {status_text}")
                    print(f"- 웹 최신 버전: {res.get('latest_version', '-')}")
                    print(f"- 상태: {up_text}")
                    if res.get("release_notes"):
                        print(f"- 참고: {res.get('release_notes')}")

                # 1) 유료 상품 또는 브라우저 다운로드 연동 모드
                if res.get("is_paid"):
                    if USE_RICH:
                        console.print(Panel(
                            "[bold yellow]🔒 유료 / 멤버십 전용 상품 안내[/bold yellow]\n\n"
                            "해당 모드(선배포 버전 등)는 제작자의 유료 / 멤버십 전용 상품입니다.\n"
                            "[bold red]유료 상품은 프로그램에서 직접 다운로드할 수 없으니 제작자의 공식 채널을 이용해 주세요.[/bold red]\n\n"
                            "[dim]※ Patreon 및 Postype에서 무료로 배포되는 모드는 프로그램이 직접 다운로드 및 자동 설치를 지원합니다.[/dim]",
                            title="[bold yellow]다운로드 안내[/bold yellow]",
                            border_style="yellow"
                        ))
                    else:
                        print("\n" + "=" * 60)
                        print("🔒 [유료 / 멤버십 전용 상품 안내]")
                        print("해당 모드(선배포 버전 등)는 제작자의 유료 / 멤버십 전용 상품입니다.")
                        print("유료 상품은 프로그램에서 직접 다운로드할 수 없으니 제작자의 공식 채널을 이용해 주세요.")
                        print("※ Patreon 및 Postype에서 무료로 배포되는 모드는 프로그램이 직접 다운로드 및 자동 설치를 지원합니다.")
                        print("=" * 60)

                    print("\n[공식 배포 채널 바로가기]")
                    if res.get("patreon_url"):
                        print(f"1. Patreon (선배포 채널): {res['patreon_url']}")
                    if res.get("postype_url"):
                        post_target = res.get("post_link") or res["postype_url"]
                        print(f"2. Postype 채널: {post_target}")
                    if res.get("naver_blog_url"):
                        print(f"3. 네이버 블로그: {res['naver_blog_url']}")
                    print("n. 브라우저 열지 않고 계속 진행")

                    ch = input("\n웹 브라우저로 열 채널을 선택하세요 (1/2/3/n) > ").strip().lower()
                    import webbrowser
                    if ch == "1" and res.get("patreon_url"):
                        webbrowser.open(res["patreon_url"])
                        print("✅ 웹 브라우저에서 Patreon 선배포 페이지가 열렸습니다.")
                    elif ch == "2" and res.get("postype_url"):
                        post_target = res.get("post_link") or res["postype_url"]
                        webbrowser.open(post_target)
                        print("✅ 웹 브라우저에서 Postype 페이지가 열렸습니다.")
                    elif ch == "3" and res.get("naver_blog_url"):
                        webbrowser.open(res["naver_blog_url"])
                        print("✅ 웹 브라우저에서 네이버 블로그가 열렸습니다.")

                elif res.get("is_early_access"):
                    page_link = res.get("page_url") or res.get("download_url") or ""
                    if USE_RICH:
                        console.print(Panel(
                            "[bold yellow]🔒 얼리 액세스(선배포) / 멤버십 전용 배포 안내[/bold yellow]\n\n"
                            "프로그램이 배포 페이지를 자체 점검한 결과, 현재 해당 모드는 [bold red]얼리 액세스(선배포) 또는 유료 멤버십 전용 상태[/bold red]여서 파일에 직접 접근할 수 없습니다.\n"
                            "아래 제작자의 공식 배포 페이지 링크를 통해 직접 확인 및 다운로드해 주세요.\n\n"
                            f"[bold cyan]🔗 제작자 배포 페이지:[/bold cyan] [underline green]{escape(page_link)}[/underline green]",
                            title="[bold yellow]얼리 액세스 안내[/bold yellow]",
                            border_style="yellow"
                        ))
                    else:
                        print("\n" + "=" * 60)
                        print("🔒 [얼리 액세스(선배포) / 멤버십 전용 배포 안내]")
                        print("프로그램이 배포 페이지를 자체 점검한 결과, 현재 해당 모드는 얼리 액세스(선배포) 또는 멤버십 전용 상태여서 파일에 직접 접근할 수 없습니다.")
                        print("아래 제작자의 공식 배포 페이지 링크를 통해 직접 다운로드해 주세요.")
                        print(f"- 제작자 배포 페이지: {page_link}")
                        print("=" * 60)

                    if page_link:
                        do_open = input(f"\n🌐 제작자 배포 페이지({page_link})를 웹 브라우저로 여시겠습니까? (y/n) > ").strip().lower()
                        if do_open == "y":
                            import webbrowser
                            webbrowser.open(page_link)
                            print("✅ 웹 브라우저에서 제작자 배포 페이지가 열렸습니다.")

                # 2) 무료 공개 배포본 (프로그램이 배포 페이지에서 직접 다운로드 가능한 모드 파일을 감지한 경우)
                elif res.get("direct_file_detected") or (res.get("download_url") and not res.get("requires_browser")):
                    detected_fname = res.get("detected_filename") or selected_mod["name"]
                    source_page = res.get("page_url") or res.get("download_url") or "-"
                    verif_note = res.get("verification_note") or "공식 배포처 및 키워드 일치 확인됨"
                    if USE_RICH:
                        console.print(Panel(
                            f"[bold green]✅ 배포 페이지에서 다운로드 가능한 무료 모드 파일을 감지했습니다![/bold green]\n\n"
                            f"[bold]📄 로컬 기준 파일:[/bold] [white]{escape(selected_mod['name'])}[/white]\n"
                            f"[bold]📦 감지된 원격 파일:[/bold] [cyan]{escape(detected_fname)}[/cyan]\n"
                            f"[bold]🔗 감지된 배포 출처:[/bold] [underline green]{escape(source_page)}[/underline green]\n"
                            f"[bold]🛡️ 안전 일치 검증:[/bold] [green]{escape(verif_note)}[/green]",
                            title="[bold green]다운로드 사전 검증 정보[/bold green]",
                            border_style="green"
                        ))
                    else:
                        print(f"\n✅ 배포 페이지에서 다운로드 가능한 무료 모드 파일({detected_fname})을 감지했습니다!")
                        print(f"  - 로컬 기준 파일: {selected_mod['name']}")
                        print(f"  - 감지된 원격 파일: {detected_fname}")
                        print(f"  - 감지된 배포 출처: {source_page}")
                        print(f"  - 안전 일치 검증: {verif_note}")

                    do_update = input("모드 파일을 감지했습니다. 지금 다운로드 하시겠습니까? (y/n) > ").strip().lower()
                    if do_update == "y":
                        target_single_name = selected_mod.get("name", detected_fname)
                        print("\n[설치 및 덮어쓰기 방식을 선택하세요]")
                        print(f"1. 지정한 파일만 덮어쓰기 ({target_single_name})")
                        print("2. 관련 파일 다 같이 덮어쓰기 (동일 배포처/압축파일 내 모든 모드 파일 일괄 덮어쓰기)")
                        print("c. 취소")
                        ow_choice = input("\n선택 (1/2/c, 기본 1) > ").strip().lower()
                        if ow_choice in ("c", "cancel", "n"):
                            print("\n[*] 다운로드를 취소했습니다.")
                        else:
                            overwrite_mode = "all" if ow_choice == "2" else "single"
                            mode_desc = "관련 파일 전체 일괄 덮어쓰기" if overwrite_mode == "all" else f"지정 파일({target_single_name}) 단독 덮어쓰기"
                            try:
                                print(f"\n🚀 [{detected_fname}] 다운로드 및 설치 중 ({mode_desc})...")
                                updated_files = updater.update_mod(selected_mod, res, overwrite_mode=overwrite_mode)
                                if isinstance(updated_files, list) and updated_files:
                                    print(f"\n🎉 총 {len(updated_files)}개 파일 자동 다운로드 및 덮어쓰기가 완료되었습니다!")
                                    for uf in updated_files:
                                        print(f"  • {uf}")
                                else:
                                    installed_label = res.get("detected_filename") or selected_mod["name"]
                                    print(f"\n🎉 [{installed_label}] 자동 다운로드 및 설치가 완료되었습니다!")
                            except Exception as e:
                                print(f"\n❌ 다운로드/설치 실패: {e}")

                elif res.get("requires_browser"):
                    print(f"\n💡 [{selected_mod['name']}] 페이지 내 직접 다운로드 파일을 감지하지 못했습니다. 아래 제작자 배포 페이지에서 직접 다운로드해 주세요.")
                    if res.get("patreon_url"):
                        print(f"  • Patreon 채널: {res['patreon_url']}")
                    if res.get("postype_url"):
                        print(f"  • Postype 채널: {res['postype_url']}")
                    if res.get("naver_blog_url"):
                        print(f"  • 네이버 블로그: {res['naver_blog_url']}")

                    target_url = res.get("page_url") or res.get("download_url", "")
                    candidate_links = res.get("candidate_links", [])

                    if len(candidate_links) > 1:
                        print(f"\n[🔗 제작자 배포 페이지 목록 (총 {len(candidate_links)}개)]")
                        for idx, item in enumerate(candidate_links, 1):
                            if len(item) == 3:
                                dom_label, title, c_url = item
                                print(f"  {idx}. [{dom_label}] {title}")
                                print(f"     ↳ {c_url}")
                            else:
                                dom_label, c_url = item
                                print(f"  {idx}. [{dom_label}] {c_url}")
                        print("  n. 브라우저 열지 않고 넘어가기")

                        ch = input(f"\n🌐 웹 브라우저로 열 채널 번호를 선택하세요 (기본 1번 / n) > ").strip().lower()
                        import webbrowser
                        if ch.isdigit() and 1 <= int(ch) <= len(candidate_links):
                            item = candidate_links[int(ch) - 1]
                            chosen_url = item[2] if len(item) == 3 else item[1]
                            chosen_label = item[0]
                            webbrowser.open(chosen_url)
                            print(f"✅ 웹 브라우저에서 [{chosen_label}] 배포 페이지가 열렸습니다.")
                        elif ch != "n":
                            item = candidate_links[0]
                            first_url = item[2] if len(item) == 3 else item[1]
                            first_label = item[0]
                            webbrowser.open(first_url)
                            print(f"✅ 웹 브라우저에서 [{first_label}] 배포 페이지가 열렸습니다.")
                    elif target_url:
                        print(f"  • 제작자 배포 페이지: {target_url}")
                        do_open = input(f"\n🌐 제작자 배포 페이지({target_url})를 웹 브라우저로 여시겠습니까? (y/n) > ").strip().lower()
                        if do_open == "y":
                            import webbrowser
                            webbrowser.open(target_url)
                            print("✅ 웹 브라우저에서 제작자 배포 페이지가 열렸습니다.")

            return True

def _print_folder_files_detail(scanner: ModScanner, target_dir: Path) -> None:
    """단일 모드 폴더 내 전체(.package / .ts4script) 파일 및 하위 폴더 위치 정보를 출력합니다."""
    file_res = scanner.scan_all_mod_files(target_dir)
    all_files = file_res["all_files"]
    pkgs = file_res["packages"]
    scrs = file_res["scripts"]
    warnings = file_res.get("warnings", [])

    if USE_RICH:
        console.print(
            f"\n[bold cyan]📂 [{escape(target_dir.name)}] 내부 파일 및 하위 폴더 목록 "
            f"(총 {len(all_files)}개: .package {len(pkgs)}개, .ts4script {len(scrs)}개):[/bold cyan]"
        )
        console.print(f"[dim]위치: {target_dir}[/dim]\n")

        if not all_files:
            console.print("[dim]포함된 .package 또는 .ts4script 파일이 없습니다.[/dim]")
        else:
            table = Table(show_lines=False)
            table.add_column("번호", justify="right", style="cyan", width=5)
            table.add_column("종류", style="bold", width=12)
            table.add_column("파일명", style="white")
            table.add_column("폴더 위치", style="dim green")

            for idx, f in enumerate(all_files, 1):
                type_styled = "[green].ts4script[/green]" if f["type"] == ".ts4script" else "[magenta].package[/magenta]"
                loc_styled = "[dim](루트)[/dim]" if f["location"] == "." else escape(f["location"])
                table.add_row(str(idx), type_styled, escape(f["name"]), loc_styled)
            console.print(table)

        if warnings:
            console.print("\n[bold yellow]⚠️ 스크립트 모드 깊이 주의 사항:[/bold yellow]")
            for w in warnings:
                console.print(f"  • [yellow]{escape(w)}[/yellow]")
    else:
        print(f"\n📂 [{target_dir.name}] 내부 파일 및 하위 폴더 목록 (총 {len(all_files)}개: .package {len(pkgs)}개, .ts4script {len(scrs)}개):")
        print(f"위치: {target_dir}\n")

        if not all_files:
            print("포함된 .package 또는 .ts4script 파일이 없습니다.")
        else:
            print(f"{'번호':>4} | {'종류':<11} | {'파일명':<45} | 폴더 위치")
            print("-" * 80)
            for idx, f in enumerate(all_files, 1):
                loc_str = "(루트)" if f["location"] == "." else f["location"]
                print(f"{idx:>4} | {f['type']:<11} | {f['name']:<45} | {loc_str}")

        if warnings:
            print("\n⚠️ 스크립트 모드 깊이 주의 사항:")
            for w in warnings:
                print(f"  • {w}")


def _handle_update_all_subfolder_inspect(scanner: ModScanner, script_mods: List[dict]) -> str:
    """보유 모드 목록에서 특정 폴더 번호(1~N) 또는 전체(a)를 선택해 내부 파일 및 하위 폴더를 확인합니다."""
    while True:
        if USE_RICH:
            console.print(f"\n[bold cyan]📁 내부 파일 및 하위 폴더를 확인할 모드를 선택하세요 (총 {len(script_mods)}개):[/bold cyan]")
            for idx, m in enumerate(script_mods, 1):
                sub_badge = f", [yellow]하위폴더: {m['subdir_count']}개[/yellow]" if m.get("subdir_count", 0) > 0 else ""
                console.print(
                    f"  [bold green]{idx:2d}.[/bold green] [bold]{escape(m['name']):<30}[/bold] "
                    f"[dim](ts4script: {m['script_count']}개, package: {m['package_count']}개{sub_badge})[/dim]"
                )
            console.print("  [bold cyan] a.[/bold cyan] 전체 모드 폴더 일괄 확인")
            console.print("  [bold yellow] b.[/bold yellow] 이전 작업 선택 메뉴로 돌아가기")
        else:
            print(f"\n📁 내부 파일 및 하위 폴더를 확인할 모드를 선택하세요 (총 {len(script_mods)}개):")
            for idx, m in enumerate(script_mods, 1):
                sub_badge = f", 하위폴더: {m['subdir_count']}개" if m.get("subdir_count", 0) > 0 else ""
                print(f"  {idx:2d}. {m['name']:<30} (ts4script: {m['script_count']}개, package: {m['package_count']}개{sub_badge})")
            print("   a. 전체 모드 폴더 일괄 확인")
            print("   b. 이전 작업 선택 메뉴로 돌아가기")

        sub_ch = input("\n폴더 선택 (번호/a/b) > ").strip().lower()
        if sub_ch in ["b", "back"]:
            return "back"
        if sub_ch in ["q", "exit"]:
            return "exit"
        if sub_ch in ["a", "all"]:
            for m in script_mods:
                _print_folder_files_detail(scanner, Path(m["path"]))
            input("\n확인을 완료했습니다. 폴더 선택 목록으로 돌아가려면 Enter 키를 누르세요...")
            continue
        if sub_ch.isdigit() and (1 <= int(sub_ch) <= len(script_mods)):
            chosen = script_mods[int(sub_ch) - 1]
            _print_folder_files_detail(scanner, Path(chosen["path"]))
            input("\n확인을 완료했습니다. 폴더 선택 목록으로 돌아가려면 Enter 키를 누르세요...")
            continue

        print("\n[!] 올바른 폴더 번호(1~{}) 또는 a, b를 입력해 주세요.".format(len(script_mods)))


def _handle_pre_update_backup(updater: ModUpdater, script_mods: List[dict]) -> None:
    """재확인된 업데이트 대상 모드 폴더 전체(스크립트/한글화 폴더들)를 백업 폴더(backups/)에 일괄 백업합니다."""
    backup_mgr = updater.backup_manager
    if not backup_mgr:
        print("\n[!] 백업 관리자가 설정되어 있지 않습니다.")
        return

    print(f"\n📦 총 {len(script_mods)}개의 업데이트 대상 모드 폴더를 일괄 백업 중입니다...")
    session_dir = backup_mgr.create_backup_session(label="PreUpdate_All")
    backed_up_folders: List[str] = []
    failed_folders: List[str] = []

    for m in script_mods:
        folder_path = Path(m["path"])
        try:
            res_path = backup_mgr.backup_item(folder_path, session_dir)
            if res_path:
                backed_up_folders.append(m["name"])
            else:
                failed_folders.append(f"{m['name']} (경로 없음)")
        except Exception as e:
            failed_folders.append(f"{m['name']} ({e})")

    if USE_RICH:
        folder_lines = "\n".join(f"  • [cyan]{escape(fn)}[/cyan]" for fn in backed_up_folders)
        fail_block = ""
        if failed_folders:
            fail_lines = "\n".join(f"  • [red]{escape(ff)}[/red]" for ff in failed_folders)
            fail_block = f"\n\n[bold red]⚠️ 백업 실패 ({len(failed_folders)}개):[/bold red]\n{fail_lines}"

        console.print(Panel(
            f"[bold green]✅ 업데이트 전 보유 모드 일괄 백업이 완료되었습니다![/bold green]\n\n"
            f"• [bold]백업 저장 경로:[/bold] {escape(str(session_dir))}\n"
            f"• [bold]백업 완료 폴더 ({len(backed_up_folders)}개):[/bold]\n{folder_lines}"
            f"{fail_block}",
            title="[bold green]💾 업데이트 전 미리 백업 완료[/bold green]",
            border_style="green"
        ))
    else:
        print("\n" + "=" * 60)
        print(f"✅ 업데이트 전 보유 모드 일괄 백업 완료! ({len(backed_up_folders)}개 폴더)")
        print(f"- 백업 저장 경로: {session_dir}")
        for fn in backed_up_folders:
            print(f"  • {fn}")
        if failed_folders:
            print(f"- 백업 실패 ({len(failed_folders)}개):")
            for ff in failed_folders:
                print(f"  • {ff}")
        print("=" * 60)


def _execute_batch_update_all(
    updater: ModUpdater,
    scanner: ModScanner,
    script_mods: List[dict],
    skip_backup: bool = True,
) -> None:
    """보유 중인 스크립트 / 한글화 모드 전체를 순차 조회하여,
    직접 다운로드 가능한 무료 모드는 일괄 자동 다운로드 및 덮어쓰기하고,
    유료/선배포/브라우저 확인 필요 모드는 결과 요약 및 링크 안내를 제공합니다.
    """
    print(f"\n🚀 총 {len(script_mods)}개 보유 모드 폴더에 대한 최신 버전 조회 및 일괄 업데이트를 시작합니다...")
    if skip_backup:
        print("   (직전 사전 일괄 백업이 완료되었으므로 개별 중복 백업은 생략합니다.)")

    auto_updated: List[tuple] = []
    manual_required: List[tuple] = []
    failed_items: List[tuple] = []
    summary_rows: List[tuple] = []

    for idx, entry in enumerate(script_mods, 1):
        folder_name = entry["name"]
        mod = updater.infer_mod_config(folder_name)
        mod["folder_name"] = folder_name

        info = scanner.detect_mod_installed(mod)
        detected_file_name = None
        detected_file_path = None
        if info.get("scripts"):
            chosen_scr = next(
                (p for p in info["scripts"] if "cmd_center" in p.name.lower() or "scripts" in p.name.lower() or "main" in p.name.lower()),
                info["scripts"][0]
            )
            detected_file_name = chosen_scr.name
            detected_file_path = str(chosen_scr)
        elif info.get("packages"):
            chosen_pkg = next(
                (p for p in info["packages"] if "!wamtik" in p.name.lower() or "_wamtik" in p.name.lower()),
                info["packages"][0]
            )
            detected_file_name = chosen_pkg.name
            detected_file_path = str(chosen_pkg)

        if detected_file_name:
            mod["name"] = detected_file_name
            f_lower = detected_file_name.lower()
            is_core_special_file = (
                (mod.get("source_type") == "mccc" and "mc_" in f_lower)
                or (mod.get("source_type") == "wickedwhims" and "turbodriver_wickedwhims" in f_lower)
                or (mod.get("source_type") == "barambyul" and "wamtik" in f_lower)
            )
            if not is_core_special_file:
                mod["source_type"] = "generic_web"
                mod["download_url"] = ""
                mod["homepage"] = ""
                mod["creator"] = "파일 내부 메타데이터 자동 감지"
        if detected_file_path:
            mod["file_path"] = detected_file_path

        display_label = f"{folder_name} ({mod['name']})" if mod.get("name") and mod["name"] != folder_name else folder_name
        print(f"\n[{idx}/{len(script_mods)}] 🔍 {display_label} 최신 배포 정보 확인 중...")

        res = updater.check_mod_update(mod)
        if "error" in res:
            err_msg = res["error"]
            print(f"   ❌ 조회 실패: {err_msg}")
            failed_items.append((folder_name, mod["name"], err_msg))
            summary_rows.append((str(idx), folder_name, mod["name"], "-", f"[red]조회 실패 ({escape(err_msg)})[/red]", f"조회 실패 ({err_msg})"))
            continue

        latest_ver = res.get("latest_version", "-")

        # 무료 직접 다운로드 가능한 경우 -> 자동 다운로드 및 일괄 덮어쓰기 실행
        if res.get("direct_file_detected") or (res.get("download_url") and not res.get("requires_browser") and not res.get("is_paid") and not res.get("is_early_access")):
            detected_fname = res.get("detected_filename") or mod["name"]
            print(f"   ⬇️ 무료 배포 파일 감지 ({detected_fname}) -> 자동 다운로드 및 덮어쓰기 진행 중...")
            try:
                updated_files = updater.update_mod(mod, res, overwrite_mode="all", skip_backup=skip_backup)
                cnt = len(updated_files) if isinstance(updated_files, list) and updated_files else 1
                print(f"   ✅ [{folder_name}] 자동 업데이트 완료 ({cnt}개 파일 덮어쓰기 완료)")
                auto_updated.append((folder_name, detected_fname, latest_ver, updated_files))
                summary_rows.append((
                    str(idx),
                    folder_name,
                    detected_fname,
                    latest_ver,
                    f"[bold green]✅ 자동 업데이트 완료 ({cnt}개 파일)[/bold green]",
                    f"자동 업데이트 완료 ({cnt}개 파일)",
                ))
            except Exception as e:
                print(f"   ❌ [{folder_name}] 다운로드/설치 실패: {e}")
                failed_items.append((folder_name, detected_fname, str(e)))
                summary_rows.append((
                    str(idx),
                    folder_name,
                    detected_fname,
                    latest_ver,
                    f"[red]❌ 설치 실패 ({escape(str(e))})[/red]",
                    f"설치 실패 ({e})",
                ))
        else:
            # 유료 / 얼리 액세스 / 브라우저 수동 확인 필요한 모드
            page_link = res.get("page_url") or res.get("download_url") or res.get("patreon_url") or res.get("postype_url") or ""
            if res.get("is_paid") or res.get("is_early_access"):
                reason_rich = "[yellow]🔒 유료/선배포 (공식 채널 확인)[/yellow]"
                reason_plain = "유료/선배포 (공식 채널 확인)"
                print(f"   🔒 [{folder_name}] 유료/선배포 전용 -> 공식 배포 링크 안내 대상")
            else:
                reason_rich = "[cyan]🌐 브라우저 직접 다운로드 필요[/cyan]"
                reason_plain = "브라우저 직접 다운로드 필요"
                print(f"   🌐 [{folder_name}] 브라우저 직접 확인 필요 ({latest_ver})")

            manual_required.append((folder_name, mod["name"], latest_ver, page_link, res))
            summary_rows.append((str(idx), folder_name, mod["name"], latest_ver, reason_rich, reason_plain))

    # 전체 결과 요약 테이블 출력
    if USE_RICH:
        res_table = Table(title="\n📊 전체 모드 업데이트 실행 결과 요약")
        res_table.add_column("번호", justify="right", style="cyan", width=4)
        res_table.add_column("모드 폴더명", style="bold white")
        res_table.add_column("기준 파일명", style="dim")
        res_table.add_column("웹 최신 버전", style="green")
        res_table.add_column("처리 결과", style="bold")

        for r_idx, r_folder, r_fname, r_ver, r_rich, _ in summary_rows:
            res_table.add_row(r_idx, escape(r_folder), escape(r_fname), escape(str(r_ver)), r_rich)
        console.print(res_table)

        console.print(Panel(
            f"• [bold green]자동 다운로드 및 덮어쓰기 완료:[/bold green] {len(auto_updated)}개 모드 폴더\n"
            f"• [bold yellow]수동/브라우저 확인 필요:[/bold yellow] {len(manual_required)}개 모드 폴더\n"
            f"• [bold red]오류 발생:[/bold red] {len(failed_items)}개 모드 폴더",
            title="[bold cyan]🎉 전체 업데이트 실행 요약[/bold cyan]",
            border_style="cyan"
        ))
    else:
        print("\n" + "=" * 70)
        print("📊 [전체 모드 업데이트 실행 결과 요약]")
        for r_idx, r_folder, r_fname, r_ver, _, r_plain in summary_rows:
            print(f"  {r_idx:>2}. {r_folder} ({r_fname}) | {r_ver} -> {r_plain}")
        print("-" * 70)
        print(f"- 자동 다운로드 및 덮어쓰기 완료: {len(auto_updated)}개")
        print(f"- 수동/브라우저 확인 필요: {len(manual_required)}개")
        print(f"- 오류 발생: {len(failed_items)}개")
        print("=" * 70)

    # 수동/브라우저 확인이 필요한 모드가 있으면 링크 목록 안내 및 선택 열기 지원
    if manual_required:
        print(f"\n[🔗 브라우저 확인/수동 다운로드 대상 모드 목록 ({len(manual_required)}개)]")
        for m_idx, (m_folder, m_fname, m_ver, m_link, _) in enumerate(manual_required, 1):
            print(f"  {m_idx:2d}. [{m_folder}] {m_fname} ({m_ver})")
            if m_link:
                print(f"      ↳ {m_link}")

        while True:
            open_ch = input("\n🌐 웹 브라우저로 열 번호를 선택하세요 (a: 전체 열기 / Enter 또는 n: 건너뛰기) > ").strip().lower()
            if open_ch in ["", "n", "no", "b", "back"]:
                break
            import webbrowser
            if open_ch in ["a", "all"]:
                opened = 0
                for _, _, _, m_link, _ in manual_required:
                    if m_link:
                        webbrowser.open(m_link)
                        opened += 1
                print(f"✅ 총 {opened}개의 배포 페이지를 웹 브라우저에서 열었습니다.")
                break
            if open_ch.isdigit() and (1 <= int(open_ch) <= len(manual_required)):
                chosen_item = manual_required[int(open_ch) - 1]
                if chosen_item[3]:
                    webbrowser.open(chosen_item[3])
                    print(f"✅ [{chosen_item[0]}] 배포 페이지를 웹 브라우저에서 열었습니다.")
                else:
                    print("[!] 연결된 배포 페이지 링크가 없습니다.")
            else:
                print(f"[!] 1~{len(manual_required)} 번호, a 또는 Enter(건너뛰기)를 입력해 주세요.")


def prepare_update_all(updater: ModUpdater, scanner: ModScanner) -> bool:
    """3번 메뉴(모드 업데이트 전체 실행) 진입 시, 바로 업데이트를 실행하지 않고
    현재 보유 중인 업데이트 대상(스크립트 / 한글화) 모드 목록을 우선 재확인합니다.
    반환값:
        True: 메인 메뉴 유지 (다른 메뉴로 전환)
        False: 프로그램 종료
    """
    user_mods_res = scanner.scan_user_mods()
    folder_mods = user_mods_res.get("folder_mods", [])

    script_mods = [
        m for m in folder_mods
        if m.get("script_count", 0) > 0 or "스크립트" in m.get("mod_type", "") or "한글" in m.get("mod_type", "")
    ]

    if not script_mods:
        print("\n[!] Mods 폴더에서 업데이트 대상(스크립트/한글화) 모드가 감지되지 않았습니다. 1번 메뉴에서 Mods 폴더 상태를 확인하세요.")
        return True

    total_pkgs = sum(m.get("package_count", 0) for m in script_mods)
    total_scripts = sum(m.get("script_count", 0) for m in script_mods)

    if USE_RICH:
        console.print(Panel(
            f"[bold cyan]전체 업데이트를 진행하기 전에 현재 보유 중인 모드를 재확인합니다.[/bold cyan]\n"
            f"[dim]대상 경로: {scanner.mods_folder}[/dim]\n\n"
            f"• [bold]감지된 업데이트 대상 모드 폴더:[/bold] [green]{len(script_mods)}개[/green]\n"
            f"• [bold]전체 .ts4script 파일 합계:[/bold] [green]{total_scripts}개[/green]\n"
            f"• [bold]전체 .package 파일 합계:[/bold] [magenta]{total_pkgs}개[/magenta]",
            title="[bold cyan]🔍 보유 모드 재확인 (전체 업데이트 대상)[/bold cyan]",
            border_style="cyan"
        ))

        mod_table = Table(title=f"📋 현재 보유 중인 스크립트 / 한글화 모드 목록 (총 {len(script_mods)}개)")
        mod_table.add_column("번호", justify="right", style="cyan", width=5)
        mod_table.add_column("모드 폴더명", style="bold white")
        mod_table.add_column("분류", justify="center")
        mod_table.add_column(".ts4script", justify="right", style="green")
        mod_table.add_column(".package", justify="right", style="magenta")
        mod_table.add_column("보조 하위폴더", justify="right", style="dim")

        for idx, m in enumerate(script_mods, 1):
            type_style = "[bold yellow]" if "한글" in m["mod_type"] else "[bold green]"
            sub_text = f"{m['subdir_count']}개" if m.get("subdir_count", 0) > 0 else "-"
            mod_table.add_row(
                str(idx),
                m["name"],
                f"{type_style}{m['mod_type']}[/]",
                f"{m['script_count']}개",
                f"{m['package_count']}개",
                sub_text
            )
        console.print(mod_table)
    else:
        print("\n" + "=" * 60)
        print("🔍 [보유 모드 재확인 (전체 업데이트 대상)]")
        print("전체 업데이트를 진행하기 전에 현재 보유 중인 모드를 재확인합니다.")
        print(f"- 대상 경로: {scanner.mods_folder}")
        print(f"- 감지된 업데이트 대상 모드 폴더: {len(script_mods)}개 (ts4script: {total_scripts}개, package: {total_pkgs}개)")
        print("=" * 60)
        print(f"\n📋 현재 보유 중인 스크립트 / 한글화 모드 목록 (총 {len(script_mods)}개):")
        for idx, m in enumerate(script_mods, 1):
            sub_text = f", 하위폴더: {m['subdir_count']}개" if m.get("subdir_count", 0) > 0 else ""
            print(f"  {idx:2d}. {m['name']:<30} [{m['mod_type']}] (ts4script: {m['script_count']}개, package: {m['package_count']}개{sub_text})")

    while True:
        print("\n[원하시는 작업을 선택하세요]")
        print("1. 다른 메뉴로 전환")
        print("2. 하위 폴더 확인하기")
        print("3. 업데이트 전 미리 백업하기")
        print("4. (이미 백업했다면) 바로 업데이트하기")
        print("5. 프로그램 종료")

        act = input("\n선택 (1/2/3/4/5) > ").strip().lower()
        if act in ["1", "b", "back"]:
            print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
            return True
        elif act == "2":
            sub_res = _handle_update_all_subfolder_inspect(scanner, script_mods)
            if sub_res == "exit":
                return False
        elif act == "3":
            _handle_pre_update_backup(updater, script_mods)
            while True:
                print("\n[원하시는 작업을 선택하세요]")
                print("1. 다른 메뉴로 전환")
                print("2. 업데이트 즉시 실행하기")

                post_bk_act = input("\n선택 (1/2) > ").strip().lower()
                if post_bk_act in ["1", "b", "back"]:
                    print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
                    return True
                elif post_bk_act == "2":
                    _execute_batch_update_all(updater, scanner, script_mods, skip_backup=True)
                    return True
                elif post_bk_act in ["q", "exit"]:
                    return False
                else:
                    print("\n[!] 1 또는 2 번호를 입력해 주세요.")
        elif act == "4":
            _execute_batch_update_all(updater, scanner, script_mods, skip_backup=True)
            return True
        elif act in ["5", "q", "exit"]:
            return False
        else:
            print("\n[!] 1, 2, 3, 4, 5 번호 중 하나를 입력해 주세요.")

def run_update_all(updater: ModUpdater, results):
    targets = [(mod, res) for mod, res in results if not res.get("error") and res.get("has_update")]
    if not targets:
        print("\n[*] 업데이트할 모드가 없습니다.")
        return

    print(f"\n🚀 총 {len(targets)}개의 모드 업데이트를 진행합니다...")
    mods = updater.load_manifest()

    for mod, res in targets:
        target_label = res.get("detected_filename") or mod["name"]
        print(f"\n-> [{target_label}] 다운로드 및 설치 중 ({res['latest_version']})...")
        try:
            updater.update_mod(mod, res)
            print(f"   ✅ [{target_label}] 업데이트 완료!")
        except Exception as e:
            print(f"   ❌ [{target_label}] 업데이트 실패: {e}")

    updater.save_manifest(mods)
    print("\n🎉 모든 업데이트 작업이 완료되었습니다!")

def list_backups(backup_mgr: BackupManager):
    backups = backup_mgr.list_backups()
    if not backups:
        print("\n[*] 생성된 백업이 없습니다.")
        return

    print(f"\n📦 백업 목록 (저장 위치: {backup_mgr.backup_dir}):")
    for idx, b in enumerate(backups, 1):
        print(f"  {idx}. {b.name}")

def main():
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent.resolve()
    else:
        base_dir = Path(__file__).parent.resolve()
    config_mgr = ConfigManager(base_dir / "config.json")
    backup_mgr = BackupManager(base_dir / config_mgr.backup_folder)
    updater = ModUpdater(config_mgr.mods_folder, base_dir / config_mgr.manifest_path, backup_mgr)
    scanner = ModScanner(config_mgr.mods_folder)

    while True:
        print_banner()
        print("\n[메뉴를 선택하세요]")
        print("1. Mods 폴더 상태 확인 및 스캔")
        print("2. 모드 업데이트 확인")
        print("3. 모드 업데이트 전체 실행")
        print("4. 백업 목록 확인")
        print("5. Mods 폴더 경로 수동 변경")
        print("q. 종료")

        choice = input("\n입력 > ").strip().lower()

        if choice == "1":
            show_status(config_mgr)
        elif choice == "2":
            if not select_and_check_mod_update(updater, scanner):
                print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
                break
            continue
        elif choice == "3":
            if not prepare_update_all(updater, scanner):
                print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
                break
            continue
        elif choice == "4":
            list_backups(backup_mgr)
        elif choice == "5":
            new_path = input("새 Mods 폴더 경로를 입력하세요: ").strip()
            if new_path:
                p = Path(new_path)
                if p.exists():
                    config_mgr.config["mods_folder"] = str(p.resolve())
                    config_mgr.save()
                    updater.mods_folder = p
                    scanner.mods_folder = p
                    print("✅ 경로가 성공적으로 저장되었습니다.")
                else:
                    print("❌ 해당 경로가 존재하지 않습니다.")
        elif choice in ["q", "exit"]:
            print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
            break
        else:
            print("\n[!] 올바른 메뉴 번호를 입력해주세요.")

        input("\n계속하려면 Enter 키를 누르세요...")

if __name__ == "__main__":
    main()
