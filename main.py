import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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
    title = "🎮 심즈 4 모드 자동 업데이터 (Sims 4 Mod Auto Updater) v0.1.4"
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
            is_root_dir = (t_dir.resolve() == scanner.mods_folder.resolve())
            file_res = scanner.scan_all_mod_files(t_dir, root_only=is_root_dir)
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
            ver_val = str(file_meta["version"]).strip()
            if re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", ver_val, flags=re.IGNORECASE):
                ver_disp = ver_val
            else:
                ver_disp = ver_val if ver_val.lower().startswith("v") else f"v{ver_val}"
            meta_rich_lines.append(f"[bold]🔖 내장 버전:[/bold] [green]{escape(ver_disp)}[/green]")
            meta_plain_lines.append(f"- 내장 버전: {ver_disp}")

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
    user_mods_res = scanner.scan_user_mods()
    folder_mods = user_mods_res["folder_mods"]
    standalone_files = user_mods_res["standalone_files"]
    mod_units = user_mods_res.get("mod_units", [])
    updatable_folder_cnt = sum(1 for f in folder_mods if f.get("is_updatable"))

    if USE_RICH:
        table = Table(title="📊 전체 모드 폴더 요약 통계")
        table.add_column("항목", style="cyan")
        table.add_column("내용", style="green")

        table.add_row("Mods 경로", str(mods_folder))
        table.add_row("폴더 존재 여부", "✅ 정상" if scan_res["exists"] else "❌ 찾을 수 없음")
        table.add_row(".package 파일 수", str(scan_res["package_count"]))
        table.add_row(".ts4script 파일 수", str(scan_res["script_count"]))
        table.add_row("총 모드 파일 수", str(scan_res["total_count"]))
        table.add_row(
            "업데이트 점검 대상 모드",
            f"[bold yellow]총 {len(mod_units)}개 개별 모드[/bold yellow] (대상 폴더 {updatable_folder_cnt}개 + 루트 파일 {len(standalone_files)}개)"
        )
        console.print(table)

        if scan_res["warnings"]:
            console.print("\n[bold yellow]⚠️ 감지된 경고 사항:[/bold yellow]")
            for w in scan_res["warnings"]:
                console.print(f"  - {w}")

        if folder_mods:
            mod_table = Table(title=f"\n📦 현재 설치된 모드 폴더 목록 (총 {len(folder_mods)}개 폴더 / 개별 모드 {len(mod_units)}개 감지됨)")
            mod_table.add_column("No", justify="center", style="dim", width=4)
            mod_table.add_column("모드 폴더명", style="bold cyan")
            mod_table.add_column("분류", justify="center")
            mod_table.add_column("포함 모드 수", justify="right", style="bold yellow")
            mod_table.add_column(".package (전체)", justify="right", style="magenta")
            mod_table.add_column(".ts4script (전체)", justify="right", style="green")
            mod_table.add_column("보조 하위폴더", justify="right", style="dim")

            for idx, f_mod in enumerate(folder_mods, 1):
                if "스크립트" in f_mod["mod_type"]:
                    type_style = "[bold green]"
                elif "패키지 모드" in f_mod["mod_type"]:
                    type_style = "[bold magenta]"
                elif "한글" in f_mod["mod_type"]:
                    type_style = "[bold yellow]"
                elif "CC" in f_mod["mod_type"]:
                    type_style = "[dim]"
                else:
                    type_style = "[cyan]"

                u_cnt = f_mod.get("unit_count", 0)
                unit_text = f"{u_cnt}개" if u_cnt > 0 else "[dim]-[/dim]"
                sub_text = f"{f_mod['subdir_count']}개" if f_mod['subdir_count'] > 0 else "-"
                mod_table.add_row(
                    str(idx),
                    f_mod["name"],
                    f"{type_style}{f_mod['mod_type']}[/]",
                    unit_text,
                    f"{f_mod['package_count']}개",
                    f"{f_mod['script_count']}개",
                    sub_text
                )
            console.print(mod_table)

        if standalone_files:
            file_names = [f["name"] for f in standalone_files]
            preview = ", ".join(file_names[:5]) + (f" 외 {len(file_names)-5}개" if len(file_names) > 5 else "")
            console.print(f"\n[bold cyan]📄 Mods 루트 단일 모드 파일 (업데이트 점검 포함):[/bold cyan] 총 {len(standalone_files)}개 ({escape(preview)})")
    else:
        print("\n[전체 모드 폴더 요약 통계]")
        print(f"- Mods 경로: {mods_folder}")
        print(f"- 폴더 존재: {'정상' if scan_res['exists'] else '찾을 수 없음'}")
        print(f"- .package: {scan_res['package_count']}개")
        print(f"- .ts4script: {scan_res['script_count']}개")
        print(f"- 업데이트 점검 대상 개별 모드: 총 {len(mod_units)}개 (대상 폴더 {updatable_folder_cnt}개 + 루트 파일 {len(standalone_files)}개)")
        if scan_res["warnings"]:
            print("\n[경고]")
            for w in scan_res["warnings"]:
                print(f"  - {w}")

        if folder_mods:
            print(f"\n[현재 설치된 모드 폴더 목록 (총 {len(folder_mods)}개 폴더 / 개별 모드 {len(mod_units)}개)]")
            for idx, f_mod in enumerate(folder_mods, 1):
                u_cnt = f_mod.get("unit_count", 0)
                u_str = f", 개별 모드: {u_cnt}개" if u_cnt > 0 else ""
                print(f"  {idx}. {f_mod['name']} [{f_mod['mod_type']}]{u_str} -> package: {f_mod['package_count']}개, script: {f_mod['script_count']}개 (하위폴더: {f_mod['subdir_count']}개)")

        if standalone_files:
            print(f"\n- Mods 루트 단일 모드 파일 (업데이트 점검 포함): 총 {len(standalone_files)}개")

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
    """1번 스캔 결과에서 업데이트 점검 대상 모드(스크립트 모드, 패키지 모드, 한글화 모드, 루트 단일 파일)들을
    자동으로 가져와 목록으로 표시하고, 사용자가 번호로 선택하여 업데이트 및 중복 감지 작업을 진행하도록 합니다.
    (u 키를 눌러 폴더별 보기 ↔ 세부 개별 모드 단위 펼쳐서 보기를 전환할 수 있습니다.)
    반환값:
        True: 메인 메뉴 유지
        False: 프로그램 종료
    """
    # 1. Mods 폴더에서 현재 감지된 모드 스캔 자료 가져오기
    user_mods_res = scanner.scan_user_mods()
    folder_mods = user_mods_res.get("folder_mods", [])
    standalone_files = user_mods_res.get("standalone_files", [])
    mod_units = user_mods_res.get("mod_units", [])

    # 2. 업데이트 점검 대상 폴더(스크립트 모드, 패키지 모드, 한글화 모드) 필터링
    script_mods = [
        m for m in folder_mods
        if m.get("is_updatable", False)
        or m.get("script_count", 0) > 0
        or "스크립트" in m.get("mod_type", "")
        or "패키지 모드" in m.get("mod_type", "")
        or "한글" in m.get("mod_type", "")
    ]

    if standalone_files:
        root_pkgs = sum(1 for f in standalone_files if (f.get("type") or f.get("suffix")) == ".package")
        root_scrs = sum(1 for f in standalone_files if (f.get("type") or f.get("suffix")) == ".ts4script")
        script_mods.append({
            "name": "(Mods 루트 단일 파일)",
            "path": str(scanner.mods_folder),
            "package_count": root_pkgs,
            "script_count": root_scrs,
            "subdir_count": 0,
            "mod_type": "스크립트 모드" if root_scrs > 0 else "패키지 모드",
            "is_updatable": True,
            "is_standalone_root": True,
            "unit_count": sum(1 for u in mod_units if u.get("is_standalone")),
        })

    if not script_mods and not mod_units:
        print("\n[!] Mods 폴더에서 업데이트 대상 모드가 감지되지 않았습니다. 1번 메뉴에서 Mods 폴더 상태를 확인하세요.")
        return True

    view_mode = "folder"  # 'folder' 또는 'unit'

    while True:
        active_list = script_mods if view_mode == "folder" else mod_units
        if view_mode == "folder":
            if USE_RICH:
                console.print(
                    f"\n[bold cyan]📋 감지된 모드 폴더 목록 (총 {len(script_mods)}개 폴더 / 세부 개별 모드 {len(mod_units)}개 감지됨):[/bold cyan]"
                )
                for idx, m in enumerate(script_mods, 1):
                    if m["script_count"] > 0:
                        script_info = f"[green]ts4script: {m['script_count']}개[/green]"
                    elif "한글" in m.get("mod_type", ""):
                        script_info = "[yellow]한글화 패키지[/yellow]"
                    else:
                        script_info = "[magenta]패키지 모드[/magenta]"
                    pkg_info = f"[magenta]package: {m['package_count']}개[/magenta]"
                    u_cnt = m.get("unit_count", 1)
                    u_badge = f", [bold yellow]포함 모드: {u_cnt}개[/bold yellow]" if u_cnt > 1 else ""
                    console.print(
                        f"  [bold green]{idx:2d}.[/bold green] [bold]{escape(m['name']):<30}[/bold] "
                        f"[dim]({script_info}, {pkg_info}{u_badge})[/dim]"
                    )
                console.print(f"  [bold cyan] u.[/bold cyan] 세부 개별 모드 단위로 펼쳐서 보기 (총 {len(mod_units)}개 개별 모드)")
                console.print("  [bold yellow] b.[/bold yellow] 메인 메뉴로 돌아가기")
            else:
                print(f"\n📋 감지된 모드 폴더 목록 (총 {len(script_mods)}개 폴더 / 세부 개별 모드 {len(mod_units)}개):")
                for idx, m in enumerate(script_mods, 1):
                    u_cnt = m.get("unit_count", 1)
                    u_badge = f", 포함 모드: {u_cnt}개" if u_cnt > 1 else ""
                    print(f"  {idx:2d}. {m['name']:<30} [{m['mod_type']}] (ts4script: {m['script_count']}개, package: {m['package_count']}개{u_badge})")
                print(f"   u. 세부 개별 모드 단위로 펼쳐서 보기 (총 {len(mod_units)}개)")
                print("   b. 메인 메뉴로 돌아가기")
        else:
            if USE_RICH:
                console.print(
                    f"\n[bold cyan]📋 세부 개별 모드 전체 목록 (총 {len(mod_units)}개 감지됨, 업데이트할 모드를 선택하세요):[/bold cyan]"
                )
                for idx, u in enumerate(mod_units, 1):
                    script_info = f"[green]ts4script: {u['script_count']}개[/green]" if u["script_count"] > 0 else "[magenta]패키지 전용[/magenta]"
                    pkg_info = f"[magenta]package: {u['package_count']}개[/magenta]"
                    console.print(
                        f"  [bold green]{idx:2d}.[/bold green] [bold]{escape(u['folder_name']):<22}[/bold] "
                        f"→ [cyan]{escape(u['primary_file_name'])}[/cyan] [dim]({script_info}, {pkg_info})[/dim]"
                    )
                console.print(f"  [bold cyan] u.[/bold cyan] 상위 폴더 단위로 묶어서 보기 (총 {len(script_mods)}개 폴더)")
                console.print("  [bold yellow] b.[/bold yellow] 메인 메뉴로 돌아가기")
            else:
                print(f"\n📋 세부 개별 모드 전체 목록 (총 {len(mod_units)}개, 업데이트할 모드를 선택하세요):")
                for idx, u in enumerate(mod_units, 1):
                    print(
                        f"  {idx:2d}. [{u['folder_name']}] {u['primary_file_name']} "
                        f"(ts4script: {u['script_count']}개, package: {u['package_count']}개)"
                    )
                print(f"   u. 상위 폴더 단위로 묶어서 보기 (총 {len(script_mods)}개 폴더)")
                print("   b. 메인 메뉴로 돌아가기")

        choice = input("\n모드 선택 (번호/u/b) > ").strip().lower()

        if choice in ["b", "back"]:
            return True
        if choice in ["q", "exit"]:
            return False
        if choice == "u":
            view_mode = "unit" if view_mode == "folder" else "folder"
            continue

        if not choice.isdigit() or not (1 <= int(choice) <= len(active_list)):
            print("\n[!] 올바른 번호를 입력해 주세요.")
            continue

        if view_mode == "folder":
            selected_entry = script_mods[int(choice) - 1]
            folder_name = selected_entry["name"]
            if selected_entry.get("is_standalone_root"):
                selected_mod = {
                    "name": "(Mods 루트 단일 파일)",
                    "folder_name": "(Mods 루트)",
                    "install_folder": "",
                    "path": str(scanner.mods_folder),
                    "is_standalone": True,
                    "source_type": "generic_web",
                    "creator": "파일 내부 메타데이터 자동 감지",
                    "folder_keywords": [],
                    "file_keywords": [],
                }
            else:
                selected_mod = updater.infer_mod_config(folder_name)
                selected_mod["folder_name"] = folder_name
                selected_mod["path"] = selected_entry.get("path")
        else:
            selected_unit = mod_units[int(choice) - 1]
            folder_name = selected_unit["folder_name"]
            primary_fn = selected_unit["primary_file_name"]
            primary_fp = selected_unit["primary_file_path"]
            selected_mod = updater.infer_mod_config(folder_name)
            if selected_mod.get("source_type") == "generic_web":
                by_file = updater.infer_mod_config(primary_fn)
                if by_file.get("source_type") != "generic_web" or by_file.get("download_url"):
                    selected_mod = by_file
            selected_mod["folder_name"] = folder_name
            selected_mod["path"] = selected_unit.get("path")
            selected_mod["is_standalone"] = selected_unit.get("is_standalone", False)
            selected_mod["unit_files"] = selected_unit.get("unit_files", [])
            selected_mod["selected_file"] = {
                "name": primary_fn,
                "full_path": primary_fp,
            }

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
                            "[bold yellow]🔒 유료 / 멤버십 전용 상품 안내 (자동 다운로드 불가)[/bold yellow]\n\n"
                            "해당 모드는 제작자의 유료 상품(또는 유료 멤버십 전용)이어서 [bold red]자동 다운로드가 불가능합니다.[/bold red]\n"
                            "아래 제작자의 공식 배포 채널 링크를 통해 직접 확인해 주세요.\n\n"
                            "[dim]※ 무료로 공개 배포되는 모드는 프로그램이 직접 다운로드 및 자동 설치를 지원합니다.[/dim]",
                            title="[bold yellow]유료 상품 안내 (자동 다운로드 불가)[/bold yellow]",
                            border_style="yellow"
                        ))
                    else:
                        print("\n" + "=" * 60)
                        print("🔒 [유료 / 멤버십 전용 상품 안내 (자동 다운로드 불가)]")
                        print("해당 모드는 제작자의 유료 상품이어서 자동 다운로드가 불가능합니다.")
                        print("아래 제작자의 공식 배포 채널 링크를 통해 직접 확인해 주세요.")
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
                    variants = res.get("variant_choices") or []
                    if len(variants) > 1:
                        detected_fname_disp = (
                            f"선택형 에디션 {len(variants)}종 감지 (동시 설치 불가 · 택1):\n"
                            + "\n".join(f"  {vi}. {v['file_name']}" for vi, v in enumerate(variants, 1))
                        )
                    else:
                        detected_fname_disp = detected_fname
                    source_page = res.get("page_url") or res.get("download_url") or "-"
                    verif_note = res.get("verification_note") or "공식 배포처 및 키워드 일치 확인됨"
                    if USE_RICH:
                        console.print(Panel(
                            f"[bold green]✅ 배포 페이지에서 다운로드 가능한 무료 모드 파일을 감지했습니다![/bold green]\n\n"
                            f"[bold]📄 로컬 기준 파일:[/bold] [white]{escape(selected_mod['name'])}[/white]\n"
                            f"[bold]📦 감지된 원격 파일:[/bold] [cyan]{escape(detected_fname_disp)}[/cyan]\n"
                            f"[bold]🔗 감지된 배포 출처:[/bold] [underline green]{escape(source_page)}[/underline green]\n"
                            f"[bold]🛡️ 안전 일치 검증:[/bold] [green]{escape(verif_note)}[/green]",
                            title="[bold green]다운로드 사전 검증 정보[/bold green]",
                            border_style="green"
                        ))
                    else:
                        print(f"\n✅ 배포 페이지에서 다운로드 가능한 무료 모드 파일({detected_fname_disp})을 감지했습니다!")
                        print(f"  - 로컬 기준 파일: {selected_mod['name']}")
                        print(f"  - 감지된 원격 파일: {detected_fname_disp}")
                        print(f"  - 감지된 배포 출처: {source_page}")
                        print(f"  - 안전 일치 검증: {verif_note}")

                    do_update = input("모드 파일을 감지했습니다. 지금 다운로드 하시겠습니까? (y/n) > ").strip().lower()
                    if do_update == "y":
                        if not _prompt_variant_choice(selected_mod.get("name", detected_fname), res):
                            print("\n[*] 다운로드를 취소했습니다.")
                        else:
                            detected_fname = res.get("detected_filename") or selected_mod["name"]
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

                elif res.get("link_not_found") or (not res.get("page_url") and not res.get("download_url")):
                    if USE_RICH:
                        console.print(Panel(
                            f"[bold yellow]❓ [{escape(selected_mod['name'])}] 링크를 찾을 수 없습니다.[/bold yellow]\n\n"
                            "파일 내부 메타데이터 및 공식 배포처 검색에서 이 모드와 일치하는 확실한 배포 링크를 찾지 못했습니다.",
                            title="[bold yellow]링크를 찾을 수 없습니다.[/bold yellow]",
                            border_style="yellow",
                        ))
                    else:
                        print(f"\n❓ [{selected_mod['name']}] 링크를 찾을 수 없습니다.")

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


def _build_mod_query_from_entry(
    updater: ModUpdater,
    scanner: ModScanner,
    entry: dict,
) -> Tuple[dict, str, Optional[str], Optional[str]]:
    """개별 모드 유닛(mod_unit) 또는 폴더 항목(folder_mod)에서 업데이트 조회용 mod 딕셔너리와
    (mod, folder_name, detected_file_name, detected_file_path)를 생성합니다.
    """
    folder_name = entry.get("folder_name") or entry.get("name") or ""
    primary_fn = entry.get("primary_file_name")
    primary_fp = entry.get("primary_file_path")

    mod = updater.infer_mod_config(folder_name)
    if primary_fn and mod.get("source_type") == "generic_web":
        by_file = updater.infer_mod_config(primary_fn)
        if by_file.get("source_type") != "generic_web" or by_file.get("download_url"):
            mod = by_file

    mod["folder_name"] = folder_name
    if entry.get("path"):
        mod["path"] = entry["path"]
    if entry.get("is_standalone"):
        mod["is_standalone"] = True
    if entry.get("unit_files"):
        mod["unit_files"] = entry["unit_files"]

    detected_file_name = primary_fn
    detected_file_path = primary_fp

    if not detected_file_name or not detected_file_path:
        info = scanner.detect_mod_installed(mod)
        if info.get("scripts"):
            chosen_scr = next(
                (p for p in info["scripts"] if "cmd_center" in p.name.lower() or "scripts" in p.name.lower() or "main" in p.name.lower()),
                info["scripts"][0],
            )
            detected_file_name = chosen_scr.name
            detected_file_path = str(chosen_scr)
        elif info.get("packages"):
            chosen_pkg = next(
                (p for p in info["packages"] if "!wamtik" in p.name.lower() or "_wamtik" in p.name.lower()),
                info["packages"][0],
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

    return mod, folder_name, detected_file_name, detected_file_path


def _handle_update_all_subfolder_inspect(scanner: ModScanner, script_mods: List[dict]) -> str:
    """보유 모드 목록에서 특정 폴더/항목 번호(1~N) 또는 전체(a)를 선택해 내부 파일 및 하위 폴더를 확인합니다."""
    while True:
        if USE_RICH:
            console.print(f"\n[bold cyan]📁 내부 파일 및 하위 폴더를 확인할 모드를 선택하세요 (총 {len(script_mods)}개):[/bold cyan]")
            for idx, m in enumerate(script_mods, 1):
                label = m.get("display_name") or m.get("name") or ""
                sub_badge = f", [yellow]하위폴더: {m['subdir_count']}개[/yellow]" if m.get("subdir_count", 0) > 0 else ""
                console.print(
                    f"  [bold green]{idx:2d}.[/bold green] [bold]{escape(label):<42}[/bold] "
                    f"[dim](ts4script: {m['script_count']}개, package: {m['package_count']}개{sub_badge})[/dim]"
                )
            console.print("  [bold cyan] a.[/bold cyan] 전체 모드 폴더 일괄 확인")
            console.print("  [bold yellow] b.[/bold yellow] 이전 작업 선택 메뉴로 돌아가기")
        else:
            print(f"\n📁 내부 파일 및 하위 폴더를 확인할 모드를 선택하세요 (총 {len(script_mods)}개):")
            for idx, m in enumerate(script_mods, 1):
                label = m.get("display_name") or m.get("name") or ""
                sub_badge = f", 하위폴더: {m['subdir_count']}개" if m.get("subdir_count", 0) > 0 else ""
                print(f"  {idx:2d}. {label:<42} (ts4script: {m['script_count']}개, package: {m['package_count']}개{sub_badge})")
            print("   a. 전체 모드 폴더 일괄 확인")
            print("   b. 이전 작업 선택 메뉴로 돌아가기")

        sub_ch = input("\n항목 선택 (번호/a/b) > ").strip().lower()
        if sub_ch in ["b", "back"]:
            return "back"
        if sub_ch in ["q", "exit"]:
            return "exit"
        if sub_ch in ["a", "all"]:
            seen_dirs = set()
            for m in script_mods:
                p = Path(m["path"])
                target_d = p.parent if p.is_file() else p
                key = str(target_d.resolve())
                if key not in seen_dirs:
                    seen_dirs.add(key)
                    _print_folder_files_detail(scanner, target_d)
            input("\n확인을 완료했습니다. 선택 목록으로 돌아가려면 Enter 키를 누르세요...")
            continue
        if sub_ch.isdigit() and (1 <= int(sub_ch) <= len(script_mods)):
            chosen = script_mods[int(sub_ch) - 1]
            p = Path(chosen["path"])
            _print_folder_files_detail(scanner, p.parent if p.is_file() else p)
            input("\n확인을 완료했습니다. 선택 목록으로 돌아가려면 Enter 키를 누르세요...")
            continue

        print("\n[!] 올바른 번호(1~{}) 또는 a, b를 입력해 주세요.".format(len(script_mods)))


def _handle_pre_update_backup(updater: ModUpdater, script_mods: List[dict]) -> None:
    """재확인된 업데이트 대상 모드 폴더 및 루트 단일 파일 전체를 백업 폴더(backups/)에 중복 없이 일괄 백업합니다."""
    backup_mgr = updater.backup_manager
    if not backup_mgr:
        print("\n[!] 백업 관리자가 설정되어 있지 않습니다.")
        return

    # 다중 모드 폴더(예: MOD, PRIO 등)가 여러 번 중복 백업되지 않도록 최상위 폴더 또는 루트 단일 파일 단위로 중복 제거
    backup_targets: List[Tuple[str, Path]] = []
    seen_target_keys: set[str] = set()
    mods_root_resolved = updater.mods_folder.resolve()

    for m in script_mods:
        raw_p = Path(m["path"])
        if not raw_p.exists():
            continue
        try:
            rel_parts = raw_p.resolve().relative_to(mods_root_resolved).parts
            if len(rel_parts) >= 1:
                top_item = updater.mods_folder / rel_parts[0]
            else:
                top_item = raw_p
        except Exception:
            top_item = raw_p

        key = str(top_item.resolve()).lower()
        if key not in seen_target_keys:
            seen_target_keys.add(key)
            backup_targets.append((top_item.name, top_item))

    print(f"\n📦 총 {len(backup_targets)}개의 업데이트 대상 폴더/파일(개별 모드 {len(script_mods)}개)을 일괄 백업 중입니다...")
    session_dir = backup_mgr.create_backup_session(label="PreUpdate_All")
    backed_up_folders: List[str] = []
    failed_folders: List[str] = []

    for label_name, target_path in backup_targets:
        try:
            res_path = backup_mgr.backup_item(target_path, session_dir)
            if res_path:
                backed_up_folders.append(label_name)
            else:
                failed_folders.append(f"{label_name} (경로 없음)")
        except Exception as e:
            failed_folders.append(f"{label_name} ({e})")

    if USE_RICH:
        folder_lines = "\n".join(f"  • [cyan]{escape(fn)}[/cyan]" for fn in backed_up_folders)
        fail_block = ""
        if failed_folders:
            fail_lines = "\n".join(f"  • [red]{escape(ff)}[/red]" for ff in failed_folders)
            fail_block = f"\n\n[bold red]⚠️ 백업 실패 ({len(failed_folders)}개):[/bold red]\n{fail_lines}"

        console.print(Panel(
            f"[bold green]✅ 업데이트 전 보유 모드 일괄 백업이 완료되었습니다![/bold green]\n\n"
            f"• [bold]백업 저장 경로:[/bold] {escape(str(session_dir))}\n"
            f"• [bold]백업 완료 항목 ({len(backed_up_folders)}개 폴더/파일, 총 {len(script_mods)}개 모드 포함):[/bold]\n{folder_lines}"
            f"{fail_block}",
            title="[bold green]💾 업데이트 전 미리 백업 완료[/bold green]",
            border_style="green"
        ))
    else:
        print("\n" + "=" * 60)
        print(f"✅ 업데이트 전 보유 모드 일괄 백업 완료! ({len(backed_up_folders)}개 항목)")
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
    """보유 중인 업데이트 대상 개별 모드 전체를 순차 조회하여,
    직접 다운로드 가능한 무료 모드는 일괄 자동 다운로드 및 덮어쓰기하고,
    유료/선배포/브라우저 확인 필요 모드는 결과 요약 및 링크 안내를 제공합니다.
    """
    print(f"\n🚀 총 {len(script_mods)}개 보유 개별 모드에 대한 최신 버전 조회 및 일괄 업데이트를 시작합니다...")
    if skip_backup:
        print("   (직전 사전 일괄 백업이 완료되었으므로 개별 중복 백업은 생략합니다.)")

    auto_updated: List[tuple] = []
    manual_required: List[tuple] = []
    failed_items: List[tuple] = []
    summary_rows: List[tuple] = []

    for idx, entry in enumerate(script_mods, 1):
        mod, folder_name, detected_file_name, detected_file_path = _build_mod_query_from_entry(
            updater, scanner, entry
        )

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
            # 링크 미발견 / 유료 / 얼리 액세스 / 브라우저 수동 확인 필요한 모드
            page_link = res.get("page_url") or res.get("download_url") or res.get("patreon_url") or res.get("postype_url") or ""
            if res.get("link_not_found") or not page_link:
                reason_rich = "[dim]❓ 링크를 찾을 수 없습니다.[/dim]"
                reason_plain = "링크를 찾을 수 없습니다."
                print(f"   ❓ [{folder_name}] 링크를 찾을 수 없습니다.")
                summary_rows.append((str(idx), folder_name, mod["name"], "링크를 찾을 수 없습니다.", reason_rich, reason_plain))
            elif res.get("is_paid"):
                reason_rich = "[yellow]🔒 유료 상품 (자동 다운로드 불가)[/yellow]"
                reason_plain = "유료 상품 (자동 다운로드 불가)"
                print(f"   🔒 [{folder_name}] 유료 상품이어서 자동 다운로드 불가 -> 공식 배포 링크 안내 대상")
                manual_required.append((folder_name, mod["name"], latest_ver, page_link, res))
                summary_rows.append((str(idx), folder_name, mod["name"], latest_ver, reason_rich, reason_plain))
            elif res.get("is_early_access"):
                reason_rich = "[yellow]🔒 선배포/멤버십 제한 (공식 채널 확인)[/yellow]"
                reason_plain = "선배포/멤버십 제한 (공식 채널 확인)"
                print(f"   🔒 [{folder_name}] 선배포/멤버십 전용 -> 공식 배포 링크 안내 대상")
                manual_required.append((folder_name, mod["name"], latest_ver, page_link, res))
                summary_rows.append((str(idx), folder_name, mod["name"], latest_ver, reason_rich, reason_plain))
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
            f"• [bold green]자동 다운로드 및 덮어쓰기 완료:[/bold green] {len(auto_updated)}개 모드\n"
            f"• [bold yellow]수동/브라우저 확인 필요:[/bold yellow] {len(manual_required)}개 모드\n"
            f"• [bold red]오류 발생:[/bold red] {len(failed_items)}개 모드",
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
    현재 보유 중인 업데이트 대상(스크립트 / 패키지 모드 / 한글화 / 루트 파일) 개별 모드 전체 목록을 우선 재확인합니다.
    반환값:
        True: 메인 메뉴 유지 (다른 메뉴로 전환)
        False: 프로그램 종료
    """
    user_mods_res = scanner.scan_user_mods()
    folder_mods = user_mods_res.get("folder_mods", [])
    mod_units = user_mods_res.get("mod_units", [])

    updatable_folders = [
        m for m in folder_mods
        if m.get("is_updatable", False)
    ]

    if not mod_units:
        print("\n[!] Mods 폴더에서 업데이트 대상 모드가 감지되지 않았습니다. 1번 메뉴에서 Mods 폴더 상태를 확인하세요.")
        return True

    total_pkgs = sum(u.get("package_count", 0) for u in mod_units)
    total_scripts = sum(u.get("script_count", 0) for u in mod_units)

    if USE_RICH:
        console.print(Panel(
            f"[bold cyan]전체 업데이트를 진행하기 전에 현재 보유 중인 모드를 재확인합니다.[/bold cyan]\n"
            f"[dim]대상 경로: {scanner.mods_folder}[/dim]\n\n"
            f"• [bold]감지된 업데이트 대상 개별 모드:[/bold] [bold yellow]{len(mod_units)}개[/bold yellow] (상위 폴더 {len(updatable_folders)}개)\n"
            f"• [bold]대상 .ts4script 파일 합계:[/bold] [green]{total_scripts}개[/green]\n"
            f"• [bold]대상 .package 파일 합계:[/bold] [magenta]{total_pkgs}개[/magenta]",
            title="[bold cyan]🔍 보유 모드 재확인 (전체 업데이트 대상)[/bold cyan]",
            border_style="cyan"
        ))

        mod_table = Table(title=f"📋 현재 보유 중인 업데이트 대상 개별 모드 목록 (총 {len(mod_units)}개)")
        mod_table.add_column("번호", justify="right", style="cyan", width=5)
        mod_table.add_column("위치 (폴더)", style="bold white")
        mod_table.add_column("기준 모드 파일명", style="cyan")
        mod_table.add_column("분류", justify="center")
        mod_table.add_column(".ts4script", justify="right", style="green")
        mod_table.add_column(".package", justify="right", style="magenta")

        for idx, u in enumerate(mod_units, 1):
            if "한글" in u["mod_type"]:
                type_style = "[bold yellow]"
            elif "패키지" in u["mod_type"]:
                type_style = "[bold magenta]"
            else:
                type_style = "[bold green]"
            mod_table.add_row(
                str(idx),
                u["folder_name"],
                u["primary_file_name"],
                f"{type_style}{u['mod_type']}[/]",
                f"{u['script_count']}개",
                f"{u['package_count']}개",
            )
        console.print(mod_table)
    else:
        print("\n" + "=" * 60)
        print("🔍 [보유 모드 재확인 (전체 업데이트 대상)]")
        print("전체 업데이트를 진행하기 전에 현재 보유 중인 모드를 재확인합니다.")
        print(f"- 대상 경로: {scanner.mods_folder}")
        print(f"- 감지된 업데이트 대상 개별 모드: {len(mod_units)}개 (ts4script: {total_scripts}개, package: {total_pkgs}개)")
        print("=" * 60)
        print(f"\n📋 현재 보유 중인 업데이트 대상 개별 모드 목록 (총 {len(mod_units)}개):")
        for idx, u in enumerate(mod_units, 1):
            print(
                f"  {idx:2d}. [{u['folder_name']}] {u['primary_file_name']} "
                f"[{u['mod_type']}] (ts4script: {u['script_count']}개, package: {u['package_count']}개)"
            )

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
            sub_res = _handle_update_all_subfolder_inspect(scanner, mod_units)
            if sub_res == "exit":
                return False
        elif act == "3":
            _handle_pre_update_backup(updater, mod_units)
            while True:
                print("\n[원하시는 작업을 선택하세요]")
                print("1. 다른 메뉴로 전환")
                print("2. 업데이트 즉시 실행하기")

                post_bk_act = input("\n선택 (1/2) > ").strip().lower()
                if post_bk_act in ["1", "b", "back"]:
                    print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
                    return True
                elif post_bk_act == "2":
                    _execute_batch_update_all(updater, scanner, mod_units, skip_backup=True)
                    return True
                elif post_bk_act in ["q", "exit"]:
                    return False
                else:
                    print("\n[!] 1 또는 2 번호를 입력해 주세요.")
        elif act == "4":
            _execute_batch_update_all(updater, scanner, mod_units, skip_backup=True)
            return True
        elif act in ["5", "q", "exit"]:
            return False
        else:
            print("\n[!] 1, 2, 3, 4, 5 번호 중 하나를 입력해 주세요.")

def _extract_local_version_token(
    detected_file_name: str,
    detected_file_path: Optional[str],
    manifest_entries: List[dict],
    folder_name: str = "",
) -> str:
    """로컬 모드 파일명, 파일 내부 메타데이터(.ts4script/.package), 폴더명(예: GSM MCCC [버전]), 또는 매니페스트 기록에서
    현재 설치된 로컬 버전 문자열을 추출합니다.
    """
    from src.finder import extract_version_from_filename, extract_mod_file_metadata

    # 1) 파일명에 명시된 버전 추출
    ver = extract_version_from_filename(detected_file_name)
    if ver:
        return ver

    # 2) 파일 내부 메타데이터(ModFileManifest / .pyc 상수 등)에서 버전 추출
    if detected_file_path:
        try:
            meta = extract_mod_file_metadata(detected_file_path)
            m_ver = (meta.get("version") or "").strip()
            if m_ver:
                if re.match(r"^20\d{2}\.\d{2}\.\d{2}$", m_ver):
                    return m_ver
                if m_ver.upper().startswith("V") and re.match(r"^V\d+[GBPR]\d+$", m_ver.upper()):
                    return m_ver.upper()
                return m_ver if m_ver.lower().startswith("v") else f"v{m_ver}"
        except Exception:
            pass

    # 3) 폴더명에 명시된 버전 추출 (예: 바람별 폴더 구조 'GSM MCCC [2026.1.1]', 'GM 모드이름 [v1.2]')
    if folder_name:
        f_ver = extract_version_from_filename(folder_name)
        if f_ver:
            return f_ver

    # 3) mods_manifest.json에 기록된 로컬 버전 확인
    t_low = (detected_file_name or "").strip().lower()
    if t_low:
        for entry in manifest_entries:
            e_name = (entry.get("name") or "").strip().lower()
            e_local = (entry.get("local_file") or "").strip().lower()
            if t_low in (e_name, e_local):
                c_ver = extract_version_from_filename(str(entry.get("current_version") or ""))
                if c_ver:
                    return c_ver
    return ""


def _compare_local_and_remote_version(local_ver: str, remote_ver_label: str, res: dict) -> Tuple[str, str, str]:
    """로컬 버전과 웹 최신 버전을 비교하여 (상태코드, Rich 표시문구, 일반 텍스트 표시문구)를 반환합니다."""
    from packaging import version
    from src.finder import extract_version_from_filename

    remote_tok = (
        extract_version_from_filename(str(remote_ver_label or ""))
        or extract_version_from_filename(str(res.get("detected_filename") or ""))
        or extract_version_from_filename(str(res.get("asset_name") or ""))
    )

    if local_ver and remote_tok:
        l_clean = local_ver.strip()
        r_clean = remote_tok.strip()

        # 1) 바람별 통합한글화모음 스타일 (예: V98G8, V98B8, V98P8)
        m_l_vg = re.match(r"^V(\d+)([GBPR])(\d+)$", l_clean, flags=re.IGNORECASE)
        m_r_vg = re.match(r"^V(\d+)([GBPR])(\d+)$", r_clean, flags=re.IGNORECASE)
        if m_l_vg and m_r_vg and m_l_vg.group(2).upper() == m_r_vg.group(2).upper():
            l_tuple = (int(m_l_vg.group(1)), int(m_l_vg.group(3)))
            r_tuple = (int(m_r_vg.group(1)), int(m_r_vg.group(3)))
            if r_tuple > l_tuple:
                return ("update_needed", "[bold yellow]🔄 업데이트 필요[/bold yellow]", "업데이트 필요")
            return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")

        # 2) 알파벳 접미사 포함 버전 (예: v185k vs v185l) 또는 일반 숫자 버전
        l_norm = l_clean.lstrip("vVaAbB")
        r_norm = r_clean.lstrip("vVaAbB")
        if l_norm.lower() == r_norm.lower() or l_norm.replace(".", "").lower() == r_norm.replace(".", "").lower():
            return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")

        # 숫자+알파벳 분리 비교 (예: 185k -> (185, 'k'))
        m_la = re.match(r"^(\d+(?:\.\d+)*)([a-zA-Z]?)$", l_norm)
        m_ra = re.match(r"^(\d+(?:\.\d+)*)([a-zA-Z]?)$", r_norm)
        if m_la and m_ra:
            try:
                l_num_s, r_num_s = m_la.group(1), m_ra.group(1)
                if re.match(r"^\d+\.\d{2,3}$", l_num_s) and re.match(r"^\d+\.\d{2,3}$", r_num_s):
                    l_maj, l_min = l_num_s.split(".")
                    r_maj, r_min = r_num_s.split(".")
                    lv_num = (int(l_maj), int(l_min.ljust(3, "0")))
                    rv_num = (int(r_maj), int(r_min.ljust(3, "0")))
                else:
                    lv_num = version.parse(l_num_s)
                    rv_num = version.parse(r_num_s)
                if rv_num > lv_num:
                    return ("update_needed", "[bold yellow]🔄 업데이트 필요[/bold yellow]", "업데이트 필요")
                if rv_num < lv_num:
                    return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")
                # 숫자 부분이 같으면 알파벳 접미사 비교
                if m_ra.group(2).lower() > m_la.group(2).lower():
                    return ("update_needed", "[bold yellow]🔄 업데이트 필요[/bold yellow]", "업데이트 필요")
                return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")
            except Exception:
                pass

        try:
            if version.parse(r_norm) > version.parse(l_norm):
                return ("update_needed", "[bold yellow]🔄 업데이트 필요[/bold yellow]", "업데이트 필요")
            return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")
        except Exception:
            if r_norm != l_norm:
                return ("update_needed", "[bold yellow]🔄 업데이트 필요[/bold yellow]", "업데이트 필요")
            return ("up_to_date", "[bold green]✅ 최신 상태[/bold green]", "최신 상태")

    # 로컬 또는 원격에 버전 숫자가 명시되어 있지 않은 경우
    return ("manual_check", "[cyan]🔍 배포처 확인 권장[/cyan]", "배포처 확인 권장 (버전 미표기)")


def _verify_local_matches_remote_zip_tail(
    folder_path: Optional[Path],
    res: dict,
    target_file_path: Optional[Path] = None,
) -> Optional[bool]:
    """원격 배포 파일(.zip Central Directory 또는 단일 .package/.ts4script 바이트 크기)을
    메모리에서 조회(디스크 저장 없음)하여 로컬 모드 파일과 일치하는지 검증합니다.
    반환값:
        True: 로컬 파일이 원격 최신본과 크기/CRC32가 일치함 (최신 상태)
        False: 원격 파일 정보가 확인되었으나 로컬 파일과 크기 또는 CRC32가 다름 (업데이트 필요)
        None: 원격 아카이브/파일 메타데이터를 직접 비교할 수 없음
    """
    dl_url = (res.get("download_url") or "").strip()
    if not dl_url or not dl_url.startswith(("http://", "https://")):
        return None
    if "mediafire.com/file/" in dl_url.lower() or "drive.google.com" in dl_url.lower():
        return None

    search_dir = folder_path if (folder_path and folder_path.exists()) else (
        target_file_path.parent if (target_file_path and target_file_path.exists()) else None
    )
    if not search_dir or not search_dir.exists():
        return None

    try:
        import struct
        import zlib
        import requests

        local_files = {
            p.name.lower(): p
            for p in search_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in (".package", ".ts4script")
        }
        if target_file_path and target_file_path.exists():
            local_files[target_file_path.name.lower()] = target_file_path

        # 1) Patreon #free_member_file=...&size=<bytes> 프래그먼트에 파일 크기가 명시된 단일 .package/.ts4script 검증
        m_frag_sz = re.search(r"[#&]size=(\d+)", dl_url)
        asset_name = str(res.get("asset_name") or res.get("detected_filename") or "").strip()
        if m_frag_sz and asset_name.lower().endswith((".package", ".ts4script")):
            remote_sz = int(m_frag_sz.group(1))
            if remote_sz > 0:
                loc_p = local_files.get(Path(asset_name).name.lower()) or target_file_path
                if loc_p and loc_p.exists():
                    return loc_p.stat().st_size == remote_sz

        clean_dl_url = dl_url.split("#")[0]
        ua_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sims4ModAutoUpdater/0.1.4",
        }

        # 2) 단일 .package / .ts4script 직링크인 경우 HEAD Content-Length 비교
        if clean_dl_url.lower().endswith((".package", ".ts4script")) or (
            asset_name.lower().endswith((".package", ".ts4script")) and not clean_dl_url.lower().endswith((".zip", ".rar", ".7z"))
        ):
            r_head = requests.head(clean_dl_url, headers=ua_headers, allow_redirects=True, timeout=8)
            cl = r_head.headers.get("Content-Length")
            if r_head.status_code == 200 and cl and cl.isdigit() and int(cl) > 0:
                loc_p = local_files.get(Path(asset_name).name.lower()) or target_file_path
                if loc_p and loc_p.exists():
                    return loc_p.stat().st_size == int(cl)
            return None

        # 3) .zip 아카이브의 끝부분(Central Directory, 16KB) 조회 (Edge CDN 등 Range 미지원 시 소형 아카이브 일반 GET 폴백)
        r = requests.get(
            clean_dl_url,
            headers={**ua_headers, "Range": "bytes=-16384"},
            timeout=8,
        )
        buf = r.content if r.status_code in (200, 206) else b""
        if b"PK\x01\x02" not in buf:
            r_full = requests.get(clean_dl_url, headers=ua_headers, stream=True, timeout=10)
            if r_full.status_code == 200:
                cl_str = r_full.headers.get("Content-Length") or "0"
                if not cl_str.isdigit() or int(cl_str) <= 15 * 1024 * 1024:
                    chunks = []
                    total_b = 0
                    for ch in r_full.iter_content(chunk_size=65536):
                        chunks.append(ch)
                        total_b += len(ch)
                        if total_b > 15 * 1024 * 1024:
                            break
                    buf = b"".join(chunks)
            r_full.close()

        if b"PK\x01\x02" not in buf:
            return None

        remote_entries = []
        pos = 0
        while True:
            idx = buf.find(b"PK\x01\x02", pos)
            if idx < 0 or idx + 46 > len(buf):
                break
            crc, _, uncomp_sz, fn_len, ex_len, cm_len = struct.unpack_from("<IIIHHH", buf, idx + 16)
            fn = buf[idx + 46 : idx + 46 + fn_len].decode("utf-8", "ignore")
            base_fn = Path(fn).name
            if base_fn.lower().endswith((".package", ".ts4script")):
                remote_entries.append((base_fn, uncomp_sz, crc))
            pos = idx + 46 + fn_len + ex_len + cm_len

        if not remote_entries:
            return None

        matched_count = 0
        mismatched_count = 0
        for base_fn, uncomp_sz, crc in remote_entries:
            loc_p = local_files.get(base_fn.lower())
            if not loc_p:
                continue
            if loc_p.stat().st_size != uncomp_sz:
                mismatched_count += 1
                continue
            loc_crc = zlib.crc32(loc_p.read_bytes()) & 0xFFFFFFFF
            if loc_crc != crc:
                mismatched_count += 1
                continue
            matched_count += 1

        if mismatched_count > 0:
            return False
        if matched_count > 0:
            return True
        return None
    except Exception:
        return None


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def _to_rel_mods_path(raw_path: Optional[str], mods_folder: Path) -> str:
    """절대 경로를 사용자 계정명이나 드라이브 경로가 노출되지 않는 Mods 기준 상대 경로(예: Mods\\폴더\\파일.package)로 변환합니다."""
    if not raw_path:
        return "-"
    try:
        p = Path(raw_path).resolve()
        m_root = mods_folder.resolve()
        if p == m_root:
            return "Mods"
        rel = p.relative_to(m_root)
        return str(Path("Mods") / rel)
    except Exception:
        try:
            return Path(raw_path).name
        except Exception:
            return "-"


def _sanitize_report_privacy(text: str, mods_folder: Path) -> str:
    """리포트 본문에 혹시라도 남아있을 수 있는 Mods 절대 경로, 프로그램 폴더 절대 경로,
    Windows 사용자 계정 경로(C:\\Users\\사용자명 등)를 모두 상대 경로 및 마스킹 문자열로 치환합니다.
    """
    out = text
    try:
        m_str = str(mods_folder.resolve())
        if m_str:
            out = out.replace(m_str, "Mods")
            out = out.replace(m_str.replace("\\", "/"), "Mods")
    except Exception:
        pass

    try:
        b_str = str(_get_base_dir())
        if b_str:
            out = out.replace(b_str, ".")
            out = out.replace(b_str.replace("\\", "/"), ".")
    except Exception:
        pass

    try:
        home_str = str(Path.home().resolve())
        if home_str:
            out = out.replace(home_str, "<USER_HOME>")
            out = out.replace(home_str.replace("\\", "/"), "<USER_HOME>")
    except Exception:
        pass

    # C:\Users\<계정명> 또는 /Users/<계정명> 패턴 정규식 마스킹
    out = re.sub(r"(?i)[a-z]:\\Users\\[^\\/\r\n]+", r"C:\\Users\\<USER>", out)
    out = re.sub(r"(?i)[a-z]:/Users/[^\\/\r\n]+", "C:/Users/<USER>", out)
    return out


def _format_metadata_for_report(meta: dict) -> List[str]:
    """extract_mod_file_metadata가 추출한 내부 메타데이터를 리포트용 문자열 리스트로 포맷합니다."""
    if not meta:
        return ["      - 내부 메타데이터: 추출 결과 없음 (빈 딕셔너리)"]
    has_meta = bool(meta.get("has_metadata"))
    manifest_name = meta.get("manifest_name") or "(없음)"
    creators = ", ".join(meta.get("creators") or []) or "(없음)"
    inferred_creator = meta.get("inferred_creator") or "(없음)"
    inferred_mod = meta.get("inferred_mod") or "(없음)"
    ver = meta.get("version") or "(없음)"
    urls = ", ".join(meta.get("urls") or []) or "(없음)"
    modules = ", ".join((meta.get("modules") or [])[:10]) or "(없음)"
    root_tunings = ", ".join((meta.get("root_tunings") or [])[:10]) or "(없음)"
    display_names = ", ".join((meta.get("display_names") or [])[:6]) or "(없음)"
    is_ww_addon = "예 (WickedWhims 애드온)" if meta.get("is_ww_addon") else "아니오"

    return [
        f"      - has_metadata (내부 단서 존재 여부): {has_meta}",
        f"      - manifest_name (ModFileManifest 모드명): {manifest_name}",
        f"      - creators (명시적 제작자 태그): {creators}",
        f"      - inferred_creator (추론된 제작자): {inferred_creator}",
        f"      - inferred_mod (추론된 모드명): {inferred_mod}",
        f"      - version (파일 내장 버전): {ver}",
        f"      - urls (파일 내장 URL): {urls}",
        f"      - modules (.ts4script 모듈명): {modules}",
        f"      - root_tunings (.package 루트 튜닝 식별자): {root_tunings}",
        f"      - display_names (내부 표시 이름): {display_names}",
        f"      - is_ww_addon (WW 애드온 여부): {is_ww_addon}",
    ]


def _build_failure_reasons_for_report(
    row: dict,
    res: dict,
    meta: dict,
) -> List[str]:
    """웹 배포처 링크 미발견 또는 버전 매칭 실패 시 구체적인 실패 원인을 분석하여 반환합니다."""
    reasons: List[str] = []
    f_diag = res.get("finder_diagnostics") or {}
    page_url = row.get("page_url") or ""
    local_ver = row.get("local_ver") or ""
    remote_ver = str(row.get("remote_ver") or "")
    verif_note = str(res.get("verification_note") or "")

    # 1) 오류 발생 여부
    if row.get("status_code") == "error" or res.get("error"):
        reasons.append(f"[네트워크/스크래퍼 오류] 조회 중 예외가 발생했습니다: {res.get('error') or row.get('status_plain')}")
        return reasons

    # 2) 웹 배포처 링크 미발견 (link_not_found)
    if res.get("link_not_found") or not page_url or remote_ver == "링크를 찾을 수 없습니다.":
        reasons.append(
            f"[카탈로그 미일치] KNOWN_CATALOG에서 로컬 파일명('{row.get('file_name')}'), "
            f"폴더명('{row.get('folder_name')}'), 내부 모드명('{meta.get('manifest_name') or meta.get('inferred_mod') or '-'}')과 일치하는 등록 항목을 찾지 못함."
        )
        if not meta.get("urls"):
            reasons.append(
                "[파일 내장 URL 없음] extract_mod_file_metadata로 바이너리/XML/매니페스트를 검사했으나 제작자가 파일 내부에 심어둔 배포처 URL이 없음."
            )
        tok_c = f_diag.get("tokenized_creator") or "(미식별)"
        tok_m = f_diag.get("tokenized_mod_title") or "(미식별)"
        tok_kws = ", ".join(f_diag.get("tokenized_keywords") or []) or "(없음)"
        reasons.append(
            f"[스마트 토큰화 분석] 추론 제작자='{tok_c}', 추론 모드명='{tok_m}', 검색 키워드=[{tok_kws}]"
        )
        if f_diag.get("failure_reason"):
            reasons.append(f"[웹 검색 실패 사유] {f_diag['failure_reason']}")
        else:
            reasons.append(
                "[웹 검색 실패 사유] 신뢰 가능한 배포 도메인(Patreon, CurseForge, MTS, Tumblr, 네이버 블로그, 포스타입, 디시 심즈갤 등)에서 "
                "오탐 방지 기준(유사도 85점 이상)을 충족하는 공식 배포 페이지를 찾지 못함."
            )
        for rej in (f_diag.get("rejected_samples") or [])[:3]:
            if len(rej) >= 5:
                r_score, r_lbl, r_tit, r_url, r_why = rej[:5]
                reasons.append(f"  ↳ [기각된 후보 ({r_score}점)] [{r_lbl}] {r_tit} ({r_url}) — 사유: {r_why}")
        return reasons

    # 3) 배포처 링크는 찾았으나 버전 매칭에 실패한 경우 (버전 미표기 / 수동 확인 필요 / 유료 / 선배포 등)
    if not local_ver or local_ver == "버전 미표기":
        reasons.append(
            f"[로컬 버전 미검출] 로컬 파일명('{row.get('file_name')}'), 폴더명('{row.get('folder_name')}'), "
            f"파일 내부 메타데이터(version='{meta.get('version') or ''}'), 매니페스트 기록 어디에도 "
            "버전 숫자(예: v1.0)나 날짜(예: 2026.03.15)가 표기되어 있지 않아 로컬 버전을 특정할 수 없음."
        )

    if res.get("is_paid"):
        reasons.append(
            f"[유료 상품 제한] 매칭된 배포처({page_url})는 유료 상품이어서 비로그인 상태에서 첨부파일 및 최신 버전 자동 확인/다운로드가 불가능함."
        )
    elif res.get("is_early_access"):
        reasons.append(
            f"[얼리 액세스/선배포 제한] 매칭된 배포처({page_url})가 현재 후원자 전용 선배포 상태여서 비로그인 상태에서 첨부파일/버전 접근이 제한됨."
        )
    elif remote_ver in ("-", "수동 확인 필요") or "수동 확인" in remote_ver:
        reasons.append(
            f"[원격 버전 미검출] 배포처 URL({page_url})에는 정상 연결되었으나, 웹페이지 제목·본문·첨부파일명에서 "
            "버전 번호/날짜 패턴이 감지되지 않거나 외부 다운로드 보호(CurseForge Cloudflare, LoversLab 로그인, 블로그 본문 등)로 인해 원격 버전을 추출하지 못함."
        )

    if verif_note and "자동 다운로드 보류" in verif_note:
        reasons.append(f"[원격 파일 유사도 안전 보류] {verif_note}")

    if not reasons:
        reasons.append(
            f"[버전 대조 미확정] 로컬 버전('{local_ver}')과 웹 최신 버전('{remote_ver}') 간 자동 비교를 확정할 수 없어 배포처 수동 확인 권장 상태로 분류됨."
        )

    return reasons


def generate_scan_diagnostic_report(
    updater: ModUpdater,
    scanner: ModScanner,
    report_path: Optional[Path] = None,
    precomputed_rows: Optional[List[dict]] = None,
) -> Tuple[Path, Dict[str, int]]:
    """Mods 폴더 전체 스캔 결과, 감지 성공 모드, 스캔 제외/병합된 폴더 및 파일 사유,
    웹 배포처 링크 미발견 및 버전 매칭 실패 상세 원인을 분석하여 scan_report.txt 파일로 저장합니다.
    """
    from datetime import datetime
    from src.finder import extract_mod_file_metadata

    if report_path is None:
        report_path = _get_base_dir() / "scan_report.txt"

    scan_summary = scanner.scan()
    diag = scanner.collect_scan_diagnostics()
    mod_units = diag.get("mod_units", [])
    manifest_entries = updater.load_manifest()

    evaluated_rows: List[dict] = []
    if precomputed_rows is not None:
        evaluated_rows = precomputed_rows
    else:
        for idx, entry in enumerate(mod_units, 1):
            mod, folder_name, detected_file_name, detected_file_path = _build_mod_query_from_entry(
                updater, scanner, entry
            )
            local_ver = _extract_local_version_token(
                detected_file_name or folder_name,
                detected_file_path,
                manifest_entries,
                folder_name=folder_name,
            )
            if local_ver:
                mod["current_version"] = local_ver

            display_label = (
                f"{folder_name} ({mod['name']})"
                if mod.get("name") and mod["name"] != folder_name
                else folder_name
            )
            print(f"  [{idx:2d}/{len(mod_units)}] 🩺 진단 중: {display_label}...")
            res = updater.check_mod_update(mod)

            if "error" in res:
                err_msg = res["error"]
                evaluated_rows.append({
                    "idx": idx,
                    "folder_name": folder_name,
                    "file_name": mod.get("name") or folder_name,
                    "file_path": detected_file_path or entry.get("primary_file_path") or "",
                    "unit_files": entry.get("unit_files", []),
                    "mod_type": entry.get("mod_type", ""),
                    "local_ver": local_ver or "버전 미표기",
                    "remote_ver": "-",
                    "status_code": "error",
                    "status_plain": f"조회 실패 ({err_msg})",
                    "page_url": "",
                    "res": res,
                })
                continue

            remote_ver_label = res.get("latest_version", "-")
            if res.get("link_not_found") or (not res.get("page_url") and not res.get("download_url")):
                remote_ver_label = "링크를 찾을 수 없습니다."
                status_code = "manual_check"
                status_plain = "링크를 찾을 수 없습니다."
            elif res.get("is_paid") and not local_ver:
                status_code = "manual_check"
                status_plain = "유료 상품 (자동 다운로드 불가)"
            else:
                status_code, _, status_plain = _compare_local_and_remote_version(
                    local_ver, remote_ver_label, res
                )

            unit_dir_path = Path(entry["path"]) if entry.get("path") else (scanner.mods_folder / folder_name)
            if unit_dir_path.is_file():
                unit_dir_path = unit_dir_path.parent
            target_fp = Path(detected_file_path) if detected_file_path else None

            if status_code == "update_needed":
                if _verify_local_matches_remote_zip_tail(unit_dir_path, res, target_file_path=target_fp) is True:
                    from src.finder import extract_version_from_filename
                    rem_tok = (
                        extract_version_from_filename(str(remote_ver_label or ""))
                        or extract_version_from_filename(str(res.get("detected_filename") or ""))
                        or extract_version_from_filename(str(res.get("asset_name") or ""))
                    )
                    if rem_tok:
                        local_ver = rem_tok
                    status_code = "up_to_date"
                    status_plain = "최신 상태"
            elif status_code == "manual_check" and res.get("direct_file_detected"):
                match_state = _verify_local_matches_remote_zip_tail(unit_dir_path, res, target_file_path=target_fp)
                if match_state is True:
                    if not local_ver:
                        local_ver = "최신본 일치"
                    status_code = "up_to_date"
                    status_plain = "최신 상태 (파일 일치)"
                elif match_state is False:
                    status_code = "update_needed"
                    status_plain = "업데이트 필요"

            page_link = (
                res.get("page_url")
                or res.get("post_link")
                or res.get("patreon_url")
                or res.get("postype_url")
                or res.get("download_url")
                or ""
            )

            evaluated_rows.append({
                "idx": idx,
                "folder_name": folder_name,
                "file_name": mod.get("name") or folder_name,
                "file_path": detected_file_path or entry.get("primary_file_path") or "",
                "unit_files": entry.get("unit_files", []),
                "mod_type": entry.get("mod_type", ""),
                "local_ver": local_ver or "버전 미표기",
                "remote_ver": remote_ver_label,
                "status_code": status_code,
                "status_plain": status_plain,
                "page_url": page_link,
                "res": res,
            })

    # 감지 성공 목록 vs 웹 링크 미발견/버전 매칭 실패 목록 분류
    matched_success_rows: List[dict] = []
    failed_or_unmatched_rows: List[dict] = []

    for r in evaluated_rows:
        res_obj = r.get("res") or {}
        page_u = r.get("page_url") or ""
        rem_v = str(r.get("remote_ver") or "")
        is_link_missing = bool(res_obj.get("link_not_found") or not page_u or rem_v == "링크를 찾을 수 없습니다.")
        is_ver_failed = bool(
            r.get("status_code") in ("manual_check", "error")
            or rem_v in ("-", "수동 확인 필요")
            or "수동 확인" in rem_v
            or "자동 다운로드 보류" in str(res_obj.get("verification_note") or "")
        )
        if not is_link_missing:
            matched_success_rows.append(r)
        if is_link_missing or is_ver_failed:
            failed_or_unmatched_rows.append(r)

    excluded_top = diag.get("excluded_top_folders", [])
    excluded_sub = diag.get("excluded_subfolders", [])
    pkg_only = diag.get("package_only_folders", [])
    multi_scr = diag.get("multi_script_folders", [])
    merged_units = diag.get("merged_unit_files", [])
    root_diag = diag.get("root_files_diagnostics", [])
    unaccounted = diag.get("unaccounted_files", [])

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append("=" * 90)
    lines.append("심즈 4 모드 자동 업데이터 (Sims 4 Mod Auto Updater) v0.1.4 - 모드 스캔 & 누락 원인 진단 리포트")
    lines.append("=" * 90)
    lines.append(f"- 생성 일시: {now_str}")
    lines.append("- 대상 Mods 경로: ./Mods (개인정보 보호를 위해 상대 경로 표기)")
    lines.append(f"- 전체 모드 파일 수: 총 {scan_summary.get('total_count', 0)}개 (.package: {scan_summary.get('package_count', 0)}개, .ts4script: {scan_summary.get('script_count', 0)}개)")
    lines.append(f"- 업데이트 점검 대상 개별 모드(Mod Unit): 총 {len(mod_units)}개")
    lines.append(f"- 웹 배포처 URL 매칭 성공 모드: {len(matched_success_rows)}개")
    lines.append(f"- 웹 배포처 링크 미발견 또는 버전 매칭 실패/수동확인 모드: {len(failed_or_unmatched_rows)}개")
    lines.append(
        f"- 스캔 제외/병합 현황: 최상위 제외 폴더 {len(excluded_top)}개 | 제외 하위폴더 {len(excluded_sub)}개 | "
        f"다중 .ts4script 폴더 {len(multi_scr)}개 | 부속 파일 병합 그룹 {len(merged_units)}개 | "
        f"루트 단일 파일 {len(root_diag)}개 | 미분류 사각지대 파일 {len(unaccounted)}개"
    )
    lines.append("=" * 90)
    lines.append("")

    # [섹션 1] 감지 성공된 모드 목록
    lines.append("━" * 90)
    lines.append(f"[1] 감지 및 배포처 매칭 성공 모드 목록 (총 {len(matched_success_rows)}개 / 전체 감지 유닛 {len(evaluated_rows)}개)")
    lines.append("━" * 90)
    if not matched_success_rows:
        lines.append("  (감지 및 배포처 매칭에 성공한 모드가 없습니다.)")
    else:
        for idx_m, r in enumerate(matched_success_rows, 1):
            res_obj = r.get("res") or {}
            meta_obj = res_obj.get("extracted_meta") or {}
            creator_name = (
                res_obj.get("matched_creator")
                or meta_obj.get("inferred_creator")
                or (meta_obj.get("creators")[0] if meta_obj.get("creators") else "")
                or "제작자 자동 감지"
            )
            f_diag = res_obj.get("finder_diagnostics") or {}
            stage = f_diag.get("match_stage") or "web_or_catalog"
            u_files = [Path(p).name for p in (r.get("unit_files") or [])]
            bundle_note = f" (그룹 내 총 {len(u_files)}개 파일 묶임)" if len(u_files) > 1 else ""

            lines.append(
                f"  {idx_m:02d}. 폴더/파일명: [{r['folder_name']}] › {r['file_name']}{bundle_note}"
            )
            lines.append(
                f"      - 상대 경로: {_to_rel_mods_path(r.get('file_path'), scanner.mods_folder)}"
            )
            lines.append(
                f"      - 분류: {r.get('mod_type') or '-'} | 매칭 방식: {stage}"
            )
            lines.append(
                f"      - 매칭된 제작자: {creator_name}"
            )
            lines.append(
                f"      - 배포처 URL: {r.get('page_url') or '-'}"
            )
            lines.append(
                f"      - 버전 및 상태: 내 로컬 버전 [{r.get('local_ver')}] / 웹 최신 버전 [{r.get('remote_ver')}] → {r.get('status_plain')}"
            )
            lines.append("")

    # [섹션 2] 스캔에서 제외되었거나 대표 파일로 병합/생략된 폴더 및 파일 목록과 사유
    lines.append("━" * 90)
    lines.append("[2] 스캔에서 제외되었거나 대표 파일로 병합/생략된 폴더 및 파일 상세 사유")
    lines.append("━" * 90)

    # 2-1. 루트 폴더(Mods/)의 단일 파일 진단
    lines.append(f"\n  ▶ 2-1. 루트 폴더(Mods/)의 단일 파일 진단 (총 {len(root_diag)}개)")
    if not root_diag:
        lines.append("    - Mods 루트 폴더에 직속 단일 파일이 없습니다.")
    else:
        for rd in root_diag:
            lines.append(f"    • 파일명: {rd['file_name']} (상대 경로: Mods\\{rd['file_name']})")
            lines.append(f"      - 처리 상태: {rd['status']}")
            lines.append(f"      - 사유: {rd['reason']}")

    # 2-2. .package 전용 폴더 분류 및 제외/포함 사유
    lines.append(f"\n  ▶ 2-2. .package 전용 폴더(.ts4script 없음) 및 CC 제외 폴더 분류 내역 (총 {len(pkg_only)}개)")
    if not pkg_only:
        lines.append("    - 해당되는 .package 전용 폴더가 없습니다.")
    else:
        for pf in pkg_only:
            lines.append(
                f"    • 폴더명: [{pf['folder_name']}] (상대 경로: Mods\\{pf['folder_name']} | .package {pf['package_count']}개, .ts4script {pf['script_count']}개)"
            )
            lines.append(f"      - 처리 상태: {pf['status']}")
            lines.append(f"      - 사유: {pf['reason']}")

    # 2-3. 한 폴더 안에 여러 개의 .ts4script가 들어있어 대표 1개 외 []개가 누락/병합된 내역
    lines.append(
        f"\n  ▶ 2-3. 한 폴더 안에 여러 개의 .ts4script가 들어있어 대표 1개 외 [N]개가 병합/생략된 폴더 (총 {len(multi_scr)}개)"
    )
    if not multi_scr:
        lines.append("    - 한 폴더 안에 2개 이상의 .ts4script가 들어있는 폴더가 없습니다.")
    else:
        for ms in multi_scr:
            lines.append(
                f"    • 폴더명: [{ms['folder_name']}] (상대 경로: Mods\\{ms['folder_name']} | .ts4script 총 {ms['total_scripts']}개)"
            )
            lines.append(
                f"      - 폴더 대표 1개: {ms['representative_script']} / 외 [{ms['omitted_in_folder_view_count']}]개: {', '.join(ms['other_scripts'])}"
            )
            lines.append(f"      - 사유: {ms['reason']}")

    # 2-4. 동일 모드 그룹(Mod Unit) 내부에서 대표 1개 외 부속 파일로 묶여 생략된 파일 내역
    lines.append(
        f"\n  ▶ 2-4. 동일 모드 그룹 내 대표 파일 1개 외 부속 파일로 묶여 개별 검색에서 생략된 항목 (총 {len(merged_units)}개 그룹)"
    )
    if not merged_units:
        lines.append("    - 다중 파일로 병합된 모드 그룹이 없습니다.")
    else:
        for mu in merged_units:
            lines.append(
                f"    • 위치/대표 파일: [{mu['folder_name']}] › 대표 1개: {mu['primary_file']} (외 [{mu['omitted_count']}]개 병합됨)"
            )
            lines.append(f"      - 사유: {mu['reason']}")
            if mu["omitted_scripts"]:
                lines.append(f"      - 생략된 부속 .ts4script ({len(mu['omitted_scripts'])}개): {', '.join(mu['omitted_scripts'])}")
            if mu["omitted_packages"]:
                pkg_preview = ", ".join(mu["omitted_packages"][:15])
                if len(mu["omitted_packages"]) > 15:
                    pkg_preview += f" 외 {len(mu['omitted_packages']) - 15}개"
                lines.append(f"      - 생략된 부속 .package ({len(mu['omitted_packages'])}개): {pkg_preview}")

    # 2-5. 모드 폴더 내부 보조/옵션/백업/CC 하위폴더로 분류되어 제외된 하위폴더
    lines.append(
        f"\n  ▶ 2-5. 모드 폴더 내부의 보조/옵션/백업/CC 하위폴더로 분류되어 스캔에서 제외된 하위폴더 (총 {len(excluded_sub)}개)"
    )
    if not excluded_sub:
        lines.append("    - 제외된 내부 보조/CC 하위폴더가 없습니다.")
    else:
        for es in excluded_sub:
            f_prev = ", ".join(es["files"][:10])
            if len(es["files"]) > 10:
                f_prev += f" 외 {len(es['files']) - 10}개"
            lines.append(
                f"    • 하위폴더 상대 경로: [Mods\\{es['folder_name']}] (.package {es['package_count']}개, .ts4script {es['script_count']}개)"
            )
            lines.append(f"      - 사유: {es['reason']}")
            lines.append(f"      - 포함 파일: {f_prev}")

    # 2-6. 최상위 제외 폴더 (빈 폴더 / 기타) 및 전체 파일 전수 대조 검증
    empty_top = [et for et in excluded_top if et["package_count"] == 0 and et["script_count"] == 0]
    lines.append(f"\n  ▶ 2-6. 모드 파일이 없는 빈 폴더 / 기타 제외 폴더 (총 {len(empty_top)}개) 및 전수 대조 검증")
    if empty_top:
        for et in empty_top:
            lines.append(f"    • 폴더 상대 경로: [Mods\\{et['folder_name']}] → 사유: {et['reason']}")
    else:
        lines.append("    - 모드 파일이 없는 빈 최상위 폴더가 없습니다.")

    if unaccounted:
        lines.append(f"    ⚠️ [미분류 누락 파일 감지: {len(unaccounted)}개]")
        for ua in unaccounted:
            lines.append(f"      • Mods\\{ua['relative_path']} → {ua['reason']}")
    else:
        lines.append(
            f"    ✅ [전수 대조 완료] Mods 폴더 내 모든 .package / .ts4script 파일(총 {scan_summary.get('total_count', 0)}개)이 "
            "단 1개의 미분류 누락도 없이 위 포함/제외/병합 항목에 100% 추적되었습니다."
        )
    lines.append("")

    # [섹션 3] 웹 배포처 링크를 못 찾았거나 버전 매칭에 실패한 모드 상세 진단
    lines.append("━" * 90)
    lines.append(
        f"[3] 웹 배포처 링크 미발견 또는 버전 매칭 실패 모드 상세 진단 (총 {len(failed_or_unmatched_rows)}개)"
    )
    lines.append("━" * 90)
    if not failed_or_unmatched_rows:
        lines.append("  🎉 모든 감지 모드의 웹 배포처 링크 및 버전 매칭이 100% 성공했습니다!")
    else:
        for idx_f, r in enumerate(failed_or_unmatched_rows, 1):
            res_obj = r.get("res") or {}
            fp_str = r.get("file_path") or ""
            meta_obj = res_obj.get("extracted_meta")
            if not meta_obj and fp_str:
                try:
                    meta_obj = extract_mod_file_metadata(fp_str)
                except Exception:
                    meta_obj = {}
            meta_obj = meta_obj or {}

            u_files_names = [Path(p).name for p in (r.get("unit_files") or [])]
            rel_fp_str = _to_rel_mods_path(fp_str, scanner.mods_folder)
            lines.append(
                f"  [{idx_f:02d}] 로컬 폴더 / 파일명: [{r['folder_name']}] › {r['file_name']}"
            )
            lines.append(f"    • 로컬 파일 상대 경로: {rel_fp_str}")
            if len(u_files_names) > 1:
                lines.append(f"    • 그룹 내 묶인 파일 목록 ({len(u_files_names)}개): {', '.join(u_files_names)}")
            lines.append(
                f"    • 버전/링크 상태: 로컬 버전='{r.get('local_ver')}' | 웹 최신 버전='{r.get('remote_ver')}' | "
                f"판정='{r.get('status_plain')}' | 배포처 URL='{r.get('page_url') or '(미발견)'}'"
            )
            lines.append("    • [extract_mod_file_metadata 추출 내부 메타데이터]:")
            lines.extend(_format_metadata_for_report(meta_obj))
            lines.append("    • [검색 실패 / 버전 매칭 실패 상세 사유]:")
            for reason_line in _build_failure_reasons_for_report(r, res_obj, meta_obj):
                lines.append(f"      - {reason_line}")
            lines.append("")

    lines.append("=" * 90)
    lines.append("End of Diagnostic Report (개인정보/절대 경로 미포함 · 이 scan_report.txt 파일을 개발자에게 전달해 주세요.)")
    lines.append("=" * 90)

    sanitized_content = _sanitize_report_privacy("\n".join(lines), scanner.mods_folder)
    report_path.write_text(sanitized_content, encoding="utf-8")

    stats = {
        "total_units": len(mod_units),
        "matched_url_count": len(matched_success_rows),
        "failed_or_manual_count": len(failed_or_unmatched_rows),
        "excluded_top_count": len(excluded_top),
        "excluded_sub_count": len(excluded_sub),
        "multi_script_count": len(multi_scr),
        "merged_unit_count": len(merged_units),
        "unaccounted_count": len(unaccounted),
    }
    return report_path, stats


def run_diagnostic_report_menu(updater: ModUpdater, scanner: ModScanner) -> bool:
    """7번 메뉴: 모드 누락 원인을 추적하는 정밀 진단 리포트(scan_report.txt)를 생성합니다."""
    if not scanner.mods_folder.exists():
        print("\n[!] Mods 폴더가 존재하지 않습니다. 6번 메뉴에서 Mods 폴더 경로를 먼저 확인해 주세요.")
        return True

    report_file = _get_base_dir() / "scan_report.txt"
    if USE_RICH:
        console.print(Panel(
            "[bold cyan]🩺 모드 누락 & 웹 매칭 원인 정밀 진단 리포트 (scan_report.txt) 생성[/bold cyan]\n\n"
            "• [bold]감지 성공 모드:[/bold] 폴더/파일명, 매칭된 제작자, 공식 배포처 URL, 버전 상태 기록\n"
            "• [bold]스캔 제외/병합 추적:[/bold] 루트 단일 파일, .package 전용/CC 폴더, 한 폴더 내 다중 .ts4script 중 대표 1개 외 [N]개 병합 사유 기록\n"
            "• [bold]웹 링크 미발견/버전 매칭 실패:[/bold] 로컬 파일명, [cyan]extract_mod_file_metadata[/cyan] 내부 메타데이터, 상세 실패 사유 기록\n"
            "• [bold green]🔒 개인정보 보호:[/bold green] 모든 경로는 상대 경로([cyan]./Mods/...[/cyan])로만 기록되어 PC 사용자명이 절대 노출되지 않습니다.",
            title="[bold cyan]📋 7. 모드 누락/매칭 진단 리포트 생성[/bold cyan]",
            border_style="cyan",
        ))
    else:
        print("\n" + "=" * 70)
        print("🩺 [7. 모드 누락 & 웹 매칭 원인 정밀 진단 리포트 (scan_report.txt) 생성]")
        print("※ 개인정보 보호를 위해 모든 경로는 상대 경로(./Mods/...)로만 기록됩니다.")
        print("=" * 70)

    saved_path, stats = generate_scan_diagnostic_report(updater, scanner, report_path=report_file)
    rel_report_disp = f"./{saved_path.name}"

    if USE_RICH:
        console.print(Panel(
            f"[bold green]✅ 진단 리포트 생성이 완료되었습니다![/bold green]\n\n"
            f"• [bold]저장된 파일 경로 (상대 경로):[/bold] [bold yellow]{escape(rel_report_disp)}[/bold yellow]\n"
            f"• [bold]감지된 개별 모드:[/bold] 총 {stats['total_units']}개 (배포처 URL 매칭 성공: [green]{stats['matched_url_count']}개[/green])\n"
            f"• [bold]스캔 제외/병합 추적:[/bold] 제외 폴더 {stats['excluded_top_count']}개, 제외 하위폴더 {stats['excluded_sub_count']}개, "
            f"다중 .ts4script 폴더 {stats['multi_script_count']}개, 부속 병합 그룹 {stats['merged_unit_count']}개\n"
            f"• [bold]링크 미발견 / 버전 수동 확인 상세 분석:[/bold] [yellow]{stats['failed_or_manual_count']}개[/yellow]\n"
            f"• [bold]미분류 사각지대 파일:[/bold] {stats['unaccounted_count']}개 (100% 전수 추적 완료)\n\n"
            "[dim]💡 모든 경로가 상대 경로로 기록되어 PC 사용자명이 노출되지 않습니다. 생성된 scan_report.txt 파일 하나만 개발자에게 보내주세요.[/dim]",
            title="[bold green]📄 scan_report.txt 생성 완료[/bold green]",
            border_style="green",
        ))
    else:
        print("\n" + "=" * 70)
        print("✅ 진단 리포트(scan_report.txt) 생성이 완료되었습니다!")
        print(f"- 저장 위치 (상대 경로): {rel_report_disp}")
        print(f"- 감지된 개별 모드: 총 {stats['total_units']}개 (URL 매칭 성공: {stats['matched_url_count']}개)")
        print(f"- 링크 미발견 / 버전 매칭 수동 확인 상세 기록: {stats['failed_or_manual_count']}개")
        print("=" * 70)

    while True:
        print("\n[원하시는 작업을 선택하세요]")
        print("1. 생성된 scan_report.txt 파일 바로 열기")
        print("2. 다른 메뉴로 전환 (메인 메뉴)")
        print("3. 프로그램 종료")
        ch = input("\n선택 (1/2/3, 기본 2) > ").strip().lower()
        if ch == "1":
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(saved_path))
                    print(f"✅ [{rel_report_disp}] 파일을 열었습니다.")
                else:
                    print(f"📄 파일 경로: {rel_report_disp}")
            except Exception as e:
                print(f"[!] 파일 열기 실패: {e}")
        elif ch in ("", "2", "b", "back"):
            return True
        elif ch in ("3", "q", "exit"):
            return False
        else:
            print("[!] 1, 2, 3 중 하나를 입력해 주세요.")


def check_update_needed_only(updater: ModUpdater, scanner: ModScanner) -> bool:
    """4번 메뉴(모드 업데이트 필요 여부 확인):
    어떠한 파일 다운로드나 덮어쓰기도 수행하지 않고(100% 읽기 전용),
    현재 보유 중인 개별 모드 전체(스크립트 모드, 패키지 모드, 한글화 모드, 루트 파일 포함)의
    로컬 버전/파일과 웹 최신 버전을 대조하여 업데이트 필요 유무만 빠르게 점검합니다.
    반환값:
        True: 메인 메뉴 유지 (다른 메뉴로 전환)
        False: 프로그램 종료
    """
    user_mods_res = scanner.scan_user_mods()
    mod_units = user_mods_res.get("mod_units", [])

    if not mod_units:
        print("\n[!] Mods 폴더에서 점검 대상 모드가 감지되지 않았습니다. 1번 메뉴에서 Mods 폴더 상태를 확인하세요.")
        return True

    if USE_RICH:
        console.print(Panel(
            f"[bold green]🔒 안심 읽기 전용 점검 모드 (파일 다운로드 및 수정 없음)[/bold green]\n"
            f"내 컴퓨터의 모드 파일을 일절 건드리지 않고, 보유 중인 개별 모드 [bold cyan]{len(mod_units)}개[/bold cyan]의\n"
            f"[bold]내 로컬 버전/파일[/bold]과 [bold]웹 최신 버전[/bold]만 비교하여 업데이트 필요 여부를 알려드립니다.",
            title="[bold cyan]🔎 4. 모드 업데이트 필요 여부 확인[/bold cyan]",
            border_style="green",
        ))
    else:
        print("\n" + "=" * 70)
        print(f"🔎 [4. 모드 업데이트 필요 여부 확인 - 읽기 전용 안심 점검 (총 {len(mod_units)}개 개별 모드)]")
        print("※ 내 컴퓨터의 파일을 일절 다운로드하거나 덮어쓰지 않고 버전만 비교합니다.")
        print("=" * 70)

    manifest_entries = updater.load_manifest()
    check_rows: List[dict] = []

    for idx, entry in enumerate(mod_units, 1):
        mod, folder_name, detected_file_name, detected_file_path = _build_mod_query_from_entry(
            updater, scanner, entry
        )

        local_ver = _extract_local_version_token(
            detected_file_name or folder_name,
            detected_file_path,
            manifest_entries,
            folder_name=folder_name,
        )
        if local_ver:
            mod["current_version"] = local_ver

        display_label = f"{folder_name} ({mod['name']})" if mod.get("name") and mod["name"] != folder_name else folder_name
        print(f"  [{idx:2d}/{len(mod_units)}] 🔎 {display_label} 버전 대조 중...")

        res = updater.check_mod_update(mod)
        if "error" in res:
            err_msg = res["error"]
            check_rows.append({
                "idx": idx,
                "folder_name": folder_name,
                "file_name": mod.get("name") or folder_name,
                "file_path": detected_file_path or entry.get("primary_file_path") or "",
                "unit_files": entry.get("unit_files", []),
                "mod_type": entry.get("mod_type", ""),
                "local_ver": local_ver or "버전 미표기",
                "remote_ver": "-",
                "status_code": "error",
                "status_rich": f"[red]❌ 조회 실패 ({escape(err_msg)})[/red]",
                "status_plain": f"조회 실패 ({err_msg})",
                "page_url": "",
                "res": res,
            })
            continue

        remote_ver_label = res.get("latest_version", "-")
        if res.get("link_not_found") or (not res.get("page_url") and not res.get("download_url")):
            remote_ver_label = "링크를 찾을 수 없습니다."
            status_code = "manual_check"
            status_rich = "[dim]❓ 링크를 찾을 수 없습니다.[/dim]"
            status_plain = "링크를 찾을 수 없습니다."
        elif res.get("is_paid") and not local_ver:
            status_code = "manual_check"
            status_rich = "[yellow]🔒 유료 상품 (자동 다운로드 불가)[/yellow]"
            status_plain = "유료 상품 (자동 다운로드 불가)"
        else:
            status_code, status_rich, status_plain = _compare_local_and_remote_version(local_ver, remote_ver_label, res)

        unit_dir_path = Path(entry["path"]) if entry.get("path") else (scanner.mods_folder / folder_name)
        if unit_dir_path.is_file():
            unit_dir_path = unit_dir_path.parent
        target_fp = Path(detected_file_path) if detected_file_path else None

        if status_code == "update_needed":
            if _verify_local_matches_remote_zip_tail(unit_dir_path, res, target_file_path=target_fp) is True:
                from src.finder import extract_version_from_filename
                rem_tok = (
                    extract_version_from_filename(str(remote_ver_label or ""))
                    or extract_version_from_filename(str(res.get("detected_filename") or ""))
                    or extract_version_from_filename(str(res.get("asset_name") or ""))
                )
                if rem_tok:
                    local_ver = rem_tok
                status_code = "up_to_date"
                status_rich = "[bold green]✅ 최신 상태[/bold green]"
                status_plain = "최신 상태"
        elif status_code == "manual_check" and res.get("direct_file_detected"):
            match_state = _verify_local_matches_remote_zip_tail(unit_dir_path, res, target_file_path=target_fp)
            if match_state is True:
                if not local_ver:
                    local_ver = "최신본 일치"
                status_code = "up_to_date"
                status_rich = "[bold green]✅ 최신 상태 (파일 일치)[/bold green]"
                status_plain = "최신 상태 (파일 일치)"
            elif match_state is False:
                status_code = "update_needed"
                status_rich = "[bold yellow]🔄 업데이트 필요[/bold yellow]"
                status_plain = "업데이트 필요"

        page_link = (
            res.get("page_url")
            or res.get("post_link")
            or res.get("patreon_url")
            or res.get("postype_url")
            or res.get("download_url")
            or ""
        )

        check_rows.append({
            "idx": idx,
            "folder_name": folder_name,
            "file_name": mod.get("name") or folder_name,
            "file_path": detected_file_path or entry.get("primary_file_path") or "",
            "unit_files": entry.get("unit_files", []),
            "mod_type": entry.get("mod_type", ""),
            "local_ver": local_ver or "버전 미표기",
            "remote_ver": remote_ver_label,
            "status_code": status_code,
            "status_rich": status_rich,
            "status_plain": status_plain,
            "page_url": page_link,
            "res": res,
        })

    report_saved_path = None
    try:
        report_saved_path, _ = generate_scan_diagnostic_report(
            updater, scanner, precomputed_rows=check_rows
        )
    except Exception:
        pass

    cnt_update = sum(1 for r in check_rows if r["status_code"] == "update_needed")
    cnt_latest = sum(1 for r in check_rows if r["status_code"] == "up_to_date")
    cnt_manual = sum(1 for r in check_rows if r["status_code"] == "manual_check")
    cnt_error = sum(1 for r in check_rows if r["status_code"] == "error")

    if USE_RICH:
        cmp_table = Table(title="\n📊 보유 모드 업데이트 필요 여부 비교표 (읽기 전용 점검)")
        cmp_table.add_column("번호", justify="right", style="cyan", width=4)
        cmp_table.add_column("위치 (폴더)", style="bold white")
        cmp_table.add_column("기준 파일명", style="dim")
        cmp_table.add_column("내 로컬 버전", justify="center", style="magenta")
        cmp_table.add_column("웹 최신 버전", justify="center", style="green")
        cmp_table.add_column("업데이트 필요 여부", justify="center")

        for r in check_rows:
            cmp_table.add_row(
                str(r["idx"]),
                escape(r["folder_name"]),
                escape(r["file_name"]),
                escape(r["local_ver"]),
                escape(str(r["remote_ver"])),
                r["status_rich"],
            )
        console.print(cmp_table)

        report_line_rich = (
            f"\n• [bold magenta]📄 진단 리포트 자동 저장 (상대 경로):[/bold magenta] ./{escape(report_saved_path.name)}"
            if report_saved_path
            else ""
        )
        console.print(Panel(
            f"• [bold yellow]🔄 업데이트 필요:[/bold yellow] {cnt_update}개 모드\n"
            f"• [bold green]✅ 최신 상태 (업데이트 불필요):[/bold green] {cnt_latest}개 모드\n"
            f"• [bold cyan]🔍 배포처 직접 확인 권장 (버전 미표기):[/bold cyan] {cnt_manual}개 모드"
            + (f"\n• [bold red]❌ 조회 실패:[/bold red] {cnt_error}개 모드" if cnt_error else "")
            + report_line_rich
            + "\n\n[dim]※ 이 점검은 읽기 전용으로 수행되었으며, 어떠한 파일도 다운로드하거나 변경하지 않았습니다.[/dim]",
            title="[bold green]✅ 업데이트 필요 여부 점검 요약[/bold green]",
            border_style="green",
        ))
    else:
        print("\n" + "=" * 78)
        print("📊 [보유 모드 업데이트 필요 여부 비교표 (읽기 전용 점검)]")
        for r in check_rows:
            print(
                f"  {r['idx']:2d}. {r['folder_name']} ({r['file_name']}) | "
                f"로컬: {r['local_ver']} | 웹 최신: {r['remote_ver']} -> {r['status_plain']}"
            )
        print("-" * 78)
        print(f"- 🔄 업데이트 필요: {cnt_update}개")
        print(f"- ✅ 최신 상태 (업데이트 불필요): {cnt_latest}개")
        print(f"- 🔍 배포처 직접 확인 권장 (버전 미표기): {cnt_manual}개")
        if cnt_error:
            print(f"- ❌ 조회 실패: {cnt_error}개")
        if report_saved_path:
            print(f"- 📄 진단 리포트 자동 저장 (상대 경로): ./{report_saved_path.name}")
        print("※ 이 점검은 읽기 전용으로 수행되었으며, 어떠한 파일도 다운로드하거나 변경하지 않았습니다.")
        print("=" * 78)

    while True:
        print("\n[원하시는 작업을 선택하세요]")
        print("1. 다른 메뉴로 전환")
        print("2. 공식 배포 페이지 웹 브라우저로 열기 (직접 눈으로 확인/수동 다운로드)")
        print("3. 생성된 진단 리포트(scan_report.txt) 열기")
        print("4. 프로그램 종료")

        act = input("\n선택 (1/2/3/4) > ").strip().lower()
        if act in ["1", "b", "back"]:
            print("\n➡️ 다른 메뉴(메인 메뉴)로 전환합니다.")
            return True
        elif act == "2":
            import webbrowser
            while True:
                open_ch = input(
                    f"\n🌐 열어볼 모드 번호를 입력하세요 (1~{len(check_rows)} / u: 업데이트 필요 항목만 열기 / a: 전체 열기 / b: 이전으로) > "
                ).strip().lower()
                if open_ch in ["", "b", "back", "n", "no"]:
                    break
                if open_ch == "u":
                    targets_u = [r for r in check_rows if r["status_code"] == "update_needed" and r.get("page_url")]
                    if not targets_u:
                        print("[*] 현재 '업데이트 필요'로 판정된 항목이 없습니다. 개별 번호나 a(전체 열기)를 이용해 주세요.")
                        continue
                    for r in targets_u:
                        webbrowser.open(r["page_url"])
                    print(f"✅ 업데이트가 필요한 {len(targets_u)}개 모드의 공식 배포 페이지를 웹 브라우저에서 열었습니다.")
                    break
                if open_ch in ["a", "all"]:
                    opened = 0
                    for r in check_rows:
                        if r.get("page_url"):
                            webbrowser.open(r["page_url"])
                            opened += 1
                    print(f"✅ 총 {opened}개 모드의 공식 배포 페이지를 웹 브라우저에서 열었습니다.")
                    break
                if open_ch.isdigit() and (1 <= int(open_ch) <= len(check_rows)):
                    chosen_r = check_rows[int(open_ch) - 1]
                    if chosen_r.get("page_url"):
                        webbrowser.open(chosen_r["page_url"])
                        print(f"✅ [{chosen_r['folder_name']}] 공식 배포 페이지를 웹 브라우저에서 열었습니다: {chosen_r['page_url']}")
                    else:
                        print("[!] 해당 모드의 공식 배포 페이지 링크를 찾지 못했습니다.")
                else:
                    print(f"[!] 1~{len(check_rows)} 번호, u, a 또는 b(이전으로)를 입력해 주세요.")
        elif act == "3":
            target_rp = report_saved_path or (_get_base_dir() / "scan_report.txt")
            if target_rp.exists() and hasattr(os, "startfile"):
                os.startfile(str(target_rp))
                print(f"✅ [{target_rp.name}] 파일을 열었습니다.")
            else:
                print(f"📄 파일 경로: {target_rp}")
        elif act in ["4", "q", "exit"]:
            return False
        else:
            print("\n[!] 1, 2, 3, 4 번호 중 하나를 입력해 주세요.")


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


def _format_size_bytes(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB ({num_bytes:,} bytes)"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB ({num_bytes:,} bytes)"
    return f"{num_bytes:,} bytes"


def _prompt_variant_choice(mod_display_name: str, res: dict) -> bool:
    """동시 설치가 불가능한 선택형 에디션(예: Political World의 Fictional Gurus vs Real-Life Gurus)이
    존재하는 경우, 사용자에게 하나를 선택하도록 안내하고 res의 다운로드 대상 정보를 갱신합니다.
    반환값: 선택 완료 시 True, 취소 시 False
    """
    variants = res.get("variant_choices") or []
    if len(variants) <= 1:
        return True

    if USE_RICH:
        lines = [
            f"[bold yellow]⚖️ [{escape(mod_display_name)}] 모드는 두 에디션을 동시에 설치할 수 없으므로 둘 중 하나를 선택해야 합니다:[/bold yellow]\n"
        ]
        for idx_v, v in enumerate(variants, 1):
            lines.append(
                f"  [bold cyan]{idx_v}.[/bold cyan] [bold white]{escape(v['file_name'])}[/bold white]\n"
                f"     ↳ [green]{escape(v.get('label', ''))}[/green]"
            )
        lines.append("\n  [bold yellow]c.[/bold yellow] 다운로드 취소")
        console.print(Panel(
            "\n".join(lines),
            title="[bold cyan]🎯 에디션 선택 (택1)[/bold cyan]",
            border_style="cyan",
        ))
    else:
        print(f"\n⚖️ [{mod_display_name}] 에디션 선택 안내 (동시 설치 불가 · 택1):")
        for idx_v, v in enumerate(variants, 1):
            print(f"  {idx_v}. {v['file_name']}")
            if v.get("label"):
                print(f"     ↳ {v['label']}")
        print("  c. 다운로드 취소")

    while True:
        v_ch = input(f"\n다운로드할 에디션 번호를 선택하세요 (1~{len(variants)}, 기본 1 / c: 취소) > ").strip().lower()
        if v_ch in ("c", "cancel", "n", "q"):
            return False
        if v_ch == "":
            chosen = variants[0]
            break
        if v_ch.isdigit() and (1 <= int(v_ch) <= len(variants)):
            chosen = variants[int(v_ch) - 1]
            break
        print(f"[!] 1~{len(variants)} 번호 또는 c(취소)를 입력해 주세요.")

    res["download_url"] = chosen["download_url"]
    res["asset_name"] = chosen["file_name"]
    res["detected_filename"] = chosen["file_name"]
    print(f"\n✅ 선택된 에디션: {chosen['file_name']}")
    return True


def _run_dev_sandbox_download_test(mod_display_name: str, virtual_fn: str, res: dict) -> bool:
    """실제 Mods 폴더를 건드리지 않고 임시 샌드박스 폴더에 파일을 다운로드하여
    무결성 검증(verify_downloaded_mod_file) 및 압축 해제(extract_zip)까지 테스트합니다.
    반환값: 자동 다운로드 및 검증 성공 여부 (True/False)
    """
    import re
    import shutil
    import tempfile
    from src.utils import calculate_sha256, download_file, extract_zip, verify_downloaded_mod_file

    dl_url = str(res.get("download_url") or "")
    is_free_member_gate = "#free_member_file=" in dl_url
    can_auto_download = bool(
        res.get("direct_file_detected")
        and not res.get("requires_browser")
        and dl_url
        and not is_free_member_gate
    )

    if not can_auto_download:
        if is_free_member_gate:
            reason = "Patreon 무료 멤버십 로그인 후 다운로드 가능한 포스트입니다. (비로그인 상태에서는 첨부파일 이름/용량만 감지)"
        elif res.get("is_early_access") or res.get("is_paid"):
            reason = "선배포(얼리 액세스) 또는 유료 후원자 전용 포스트여서 직접 다운로드가 제한됩니다."
        else:
            reason = "외부 배포처(CurseForge Cloudflare 보안, LoversLab 로그인 필수 등) 정책상 브라우저 수동 다운로드가 필요한 모드입니다."

        if USE_RICH:
            console.print(Panel(
                f"[bold yellow]⚠️ [{escape(mod_display_name)}] 모드는 자동 다운로드 대상이 아닙니다.[/bold yellow]\n"
                f"[bold]사유:[/bold] {escape(reason)}",
                title="[bold yellow]🧪 자동 다운로드 테스트 안내[/bold yellow]",
                border_style="yellow",
            ))
        else:
            print(f"\n⚠️ [{mod_display_name}] 자동 다운로드 불가: {reason}")
        return False

    if not _prompt_variant_choice(mod_display_name, res):
        print("\n[*] 에디션 선택을 취소했습니다.")
        return False

    dl_url = str(res.get("download_url") or "")
    raw_asset_name = res.get("asset_name") or res.get("detected_filename") or f"{virtual_fn}.zip"
    asset_name = re.sub(r'[<>:"/\\|?*]+', "_", str(raw_asset_name)).strip()
    if not asset_name.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
        asset_name += ".zip"

    is_multi_bundle = bool(res.get("is_multi_file_bundle"))
    all_remote_files = res.get("all_remote_files") or []
    display_dl_label = (
        res.get("detected_filename")
        if is_multi_bundle and res.get("detected_filename")
        else asset_name
    )

    print(f"\n📥 [임시 테스트 폴더] '{display_dl_label}' 실제 다운로드 및 무결성 검증 중...")
    try:
        with tempfile.TemporaryDirectory(prefix="s4mod_dev_test_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            extract_dir = tmp_path / "extracted_mods"
            extract_dir.mkdir(parents=True, exist_ok=True)

            if is_multi_bundle and all_remote_files:
                file_size = 0
                sha_short = ""
                extracted_files: list[Path] = []
                for rem_fn, rem_dl in all_remote_files:
                    if not rem_fn or not rem_dl:
                        continue
                    clean_fn = re.sub(r'[<>:"/\\|?*]+', "_", str(rem_fn)).strip()
                    if not clean_fn.lower().endswith((".package", ".ts4script")):
                        continue
                    sub_dest = tmp_path / clean_fn
                    download_file(
                        rem_dl,
                        sub_dest,
                        page_url=res.get("page_url") or "",
                        target_mod_name=clean_fn,
                    )
                    verify_downloaded_mod_file(
                        sub_dest,
                        expected_target_name=clean_fn,
                        target_dir=extract_dir,
                    )
                    if sub_dest.exists():
                        file_size += sub_dest.stat().st_size
                        if not sha_short:
                            sha_short = calculate_sha256(sub_dest)[:12]
                        copied = extract_dir / sub_dest.name
                        shutil.copy2(sub_dest, copied)
                        extracted_files.append(copied)
            else:
                dl_dest = tmp_path / asset_name
                download_file(
                    dl_url,
                    dl_dest,
                    page_url=res.get("page_url") or "",
                    target_mod_name=virtual_fn,
                )

                file_size = dl_dest.stat().st_size if dl_dest.exists() else 0
                sha_short = calculate_sha256(dl_dest)[:12] if dl_dest.exists() else "-"

                verify_downloaded_mod_file(
                    dl_dest,
                    expected_target_name=virtual_fn,
                    target_dir=extract_dir,
                )

                extracted_files = []
                if dl_dest.suffix.lower() in (".zip", ".rar", ".7z"):
                    extracted_files = extract_zip(dl_dest, extract_dir, overwrite_mode="all")
                else:
                    copied = extract_dir / dl_dest.name
                    shutil.copy2(dl_dest, copied)
                    extracted_files = [copied]

            file_rows = [
                (ef.name, _format_size_bytes(ef.stat().st_size))
                for ef in extracted_files
                if ef.exists()
            ]

        if USE_RICH:
            console.print(Panel(
                f"[bold green]✅ [{escape(mod_display_name)}] 실제 자동 다운로드 및 무결성 검증 성공![/bold green]\n\n"
                f"[bold]📦 다운로드된 파일명:[/bold] [cyan]{escape(str(display_dl_label))}[/cyan]\n"
                f"[bold]📊 다운로드 파일 총 용량:[/bold] [green]{escape(_format_size_bytes(file_size))}[/green]\n"
                f"[bold]🔑 대표 파일 SHA-256 (앞 12자리):[/bold] {escape(sha_short)}\n"
                f"[bold]🛡️ 무결성/포맷 검증:[/bold] [bold green]통과 (HTML 오탐 아님, 유효한 심즈 4 모드/압축파일 확인)[/bold green]\n"
                f"[bold]📂 확보된 모드 파일 수:[/bold] 총 {len(file_rows)}개\n"
                f"[dim]🧹 검증 완료 후 임시 테스트 폴더는 자동 삭제되었습니다. (실제 Mods 폴더 영향 없음)[/dim]",
                title="[bold green]🧪 자동 다운로드 & 압축해제 테스트 결과[/bold green]",
                border_style="green",
            ))
            if file_rows:
                ext_table = Table(title="📂 다운로드/추출된 내부 모드 파일 목록")
                ext_table.add_column("번호", justify="right", style="cyan", width=5)
                ext_table.add_column("모드 파일명 (.package / .ts4script)", style="bold white")
                ext_table.add_column("파일 크기", justify="right", style="green")
                for idx_f, (fn_str, sz_str) in enumerate(file_rows, 1):
                    ext_table.add_row(str(idx_f), escape(fn_str), escape(sz_str))
                console.print(ext_table)
        else:
            print(f"\n✅ [{mod_display_name}] 자동 다운로드 및 압축해제 검증 성공!")
            print(f"- 다운로드된 파일: {display_dl_label} ({_format_size_bytes(file_size)})")
            print(f"- 확보된 모드 파일 수: {len(file_rows)}개")
            for idx_f, (fn_str, sz_str) in enumerate(file_rows, 1):
                print(f"  {idx_f}. {fn_str} ({sz_str})")
            print("🧹 임시 테스트 폴더가 자동 삭제되었습니다. (실제 Mods 폴더 영향 없음)")
        return True
    except Exception as e:
        if USE_RICH:
            console.print(Panel(
                f"[bold red]❌ 자동 다운로드/검증 중 오류가 발생했습니다:[/bold red]\n{escape(str(e))}",
                title="[bold red]🧪 자동 다운로드 테스트 실패[/bold red]",
                border_style="red",
            ))
        else:
            print(f"\n❌ 자동 다운로드 테스트 실패: {e}")
        return False


def run_developer_catalog_test(updater: ModUpdater) -> bool:
    """개발자 전용 숨김 모드 (메인 메뉴에서 'dev' 또는 'test' 입력 시 진입):
    실제 모드 파일을 설치하지 않고도 KNOWN_CATALOG에 등록된 전체 모드의
    내장 제작자, 내부 식별 모드명, 내장 버전, 웹 최신 버전, 원격 감지 파일, 배포 링크를 테스트합니다.
    반환값:
        True: 메인 메뉴 유지
        False: 프로그램 종료
    """
    from src.finder import KNOWN_CATALOG, check_known_catalog

    while True:
        if USE_RICH:
            console.print(Panel(
                "[bold magenta]🧪 개발자 전용 카탈로그 시뮬레이션 모드 (일반 사용자 비노출)[/bold magenta]\n"
                "Mods 폴더에 파일을 설치하지 않고도 카탈로그에 등록된 모드의 메타데이터 및 웹 최신 배포 정보를 바로 점검합니다.",
                title="[bold magenta]🛠️ Developer Test Mode[/bold magenta]",
                border_style="magenta",
            ))
            cat_table = Table(title=f"📋 카탈로그 등록 모드 목록 (총 {len(KNOWN_CATALOG)}개)")
            cat_table.add_column("번호", justify="right", style="cyan", width=5)
            cat_table.add_column("식별 모드명", style="bold white")
            cat_table.add_column("내장 제작자", style="cyan")
            cat_table.add_column("기준 버전", justify="center", style="green")
            cat_table.add_column("대표 배포처", style="dim")

            for idx, item in enumerate(KNOWN_CATALOG, 1):
                mod_label = item.get("mod_title") or item.get("name") or "-"
                creator = item.get("creator") or "-"
                raw_v = str(item.get("version") or "").strip()
                if raw_v:
                    ver = raw_v if (raw_v.lower().startswith("v") or re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", raw_v, flags=re.IGNORECASE)) else f"v{raw_v}"
                else:
                    ver = "수동 확인 필요"
                first_link = item["links"][0][2] if item.get("links") else "-"
                cat_table.add_row(str(idx), escape(mod_label), escape(creator), escape(ver), escape(first_link))
            console.print(cat_table)
            console.print("  [bold yellow] b.[/bold yellow] 메인 메뉴로 돌아가기")
        else:
            print("\n" + "=" * 70)
            print("🧪 [개발자 전용 카탈로그 시뮬레이션 모드]")
            for idx, item in enumerate(KNOWN_CATALOG, 1):
                mod_label = item.get("mod_title") or item.get("name") or "-"
                creator = item.get("creator") or "-"
                raw_v = str(item.get("version") or "").strip()
                ver = (raw_v if (raw_v.lower().startswith("v") or re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", raw_v, flags=re.IGNORECASE)) else f"v{raw_v}") if raw_v else "수동 확인 필요"
                print(f"  {idx:2d}. {mod_label} | 제작자: {creator} | 버전: {ver}")
            print("   b. 메인 메뉴로 돌아가기")
            print("=" * 70)

        ch = input("\n점검할 모드 번호 선택 (1~{} / b: 메인 메뉴) > ".format(len(KNOWN_CATALOG))).strip().lower()
        if ch in ["b", "back"]:
            return True
        if ch in ["q", "exit"]:
            return False
        if not ch.isdigit() or not (1 <= int(ch) <= len(KNOWN_CATALOG)):
            print("\n[!] 올바른 번호를 입력해 주세요.")
            continue

        item = KNOWN_CATALOG[int(ch) - 1]
        sample_kw = item["keywords"][0] if item.get("keywords") else item["name"]
        virtual_fn = sample_kw if sample_kw.lower().endswith((".package", ".ts4script", ".zip")) else f"{sample_kw}.package"
        cat_info = check_known_catalog(virtual_fn) or check_known_catalog(item["name"]) or {}

        creator_disp = cat_info.get("creator") or item.get("creator") or "자동 감지"
        mod_title_disp = cat_info.get("mod_title") or item.get("mod_title") or item.get("name") or virtual_fn
        ver_raw = cat_info.get("version") or item.get("version") or ""
        ver_disp = (ver_raw if (ver_raw.lower().startswith("v") or re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", ver_raw, flags=re.IGNORECASE)) else f"v{ver_raw}") if ver_raw else "(버전 미표기 / 수동 확인)"

        if USE_RICH:
            console.print(Panel(
                f"[bold green]선택된 테스트 항목은 [{escape(item['name'])}]입니다. (미설치 가상 점검)[/bold green]\n\n"
                f"[bold]🧪 가상 파일명:[/bold] {escape(virtual_fn)}\n"
                f"[bold]👤 내장 제작자(Creator):[/bold] [cyan]{escape(creator_disp)}[/cyan]\n"
                f"[bold]📌 내부 식별 모드명:[/bold] {escape(mod_title_disp)}\n"
                f"[bold]🔖 내장 버전:[/bold] [green]{escape(ver_disp)}[/green]",
                title=f"[bold magenta]{escape(item['name'])} 내부 메타데이터 시뮬레이션[/bold magenta]",
                border_style="magenta",
            ))
        else:
            print("\n" + "=" * 60)
            print(f"선택된 테스트 항목: [{item['name']}]")
            print(f"- 가상 파일명: {virtual_fn}")
            print(f"- 내장 제작자(Creator): {creator_disp}")
            print(f"- 내부 식별 모드명: {mod_title_disp}")
            print(f"- 내장 버전: {ver_disp}")
            print("=" * 60)

        while True:
            print("\n[원하시는 작업을 선택하세요]")
            print("1. 웹에서 최신 버전/배포 페이지 검색 (자동 다운로드 지원 여부 확인)")
            print("2. 실제 파일 자동 다운로드 및 압축해제 테스트 (임시 폴더 안전 검증)")
            print("3. 카탈로그 목록으로 돌아가기")
            print("4. 메인 메뉴로 전환")
            print("5. 프로그램 종료")

            sub_act = input("\n선택 (1/2/3/4/5) > ").strip().lower()
            if sub_act == "3":
                break
            elif sub_act == "4":
                return True
            elif sub_act in ["5", "q", "exit"]:
                return False
            elif sub_act in ("1", "2"):
                selected_mod = updater.infer_mod_config(item["name"])
                selected_mod["name"] = virtual_fn
                if selected_mod.get("source_type") not in ("mccc", "wickedwhims", "barambyul"):
                    selected_mod["source_type"] = "generic_web"

                print(f"\n🌐 [{item['name']}] 원격 배포 페이지 점검 중입니다...")
                res = updater.check_mod_update(selected_mod)
                if "error" in res:
                    print(f"\n❌ 웹 검색 실패: {res['error']}")
                else:
                    up_text = res.get("status_label") or ("🚀 최신 버전 배포 중" if res.get("has_update") else "수동 등록 필요")
                    page_link = (
                        res.get("page_url")
                        or res.get("post_link")
                        or res.get("patreon_url")
                        or res.get("postype_url")
                        or res.get("download_url")
                        or ""
                    )
                    dl_url = str(res.get("download_url") or "")
                    is_free_member_gate = "#free_member_file=" in dl_url
                    can_auto_download = bool(
                        res.get("direct_file_detected")
                        and not res.get("requires_browser")
                        and dl_url
                        and not is_free_member_gate
                    )
                    if can_auto_download:
                        auto_dl_label = "✅ 자동 다운로드 가능 (직접 링크 확보됨)"
                    elif is_free_member_gate:
                        auto_dl_label = "🔑 조건부 (Patreon 무료 회원 로그인 필요 - 첨부파일명 감지됨)"
                    elif res.get("is_early_access") or res.get("is_paid"):
                        auto_dl_label = "🔒 불가 - 선배포/유료 멤버십 제한 (수동 다운로드 안내)"
                    else:
                        auto_dl_label = "⚠️ 불가 - 외부 사이트 보안/로그인 필요 (수동 다운로드 안내)"

                    bundle_fns = res.get("bundle_filenames") or []
                    variants = res.get("variant_choices") or []
                    if len(variants) > 1:
                        detected_files_disp = (
                            f"선택형 에디션 {len(variants)}종 감지 (동시 설치 불가 · 택1):\n"
                            + "\n".join(f"• {idx_v}번: {v['file_name']}" for idx_v, v in enumerate(variants, 1))
                        )
                    elif len(bundle_fns) > 1:
                        detected_files_disp = f"총 {len(bundle_fns)}개 구성 파일 일괄 인식:\n" + "\n".join(f"• {fn}" for fn in bundle_fns)
                    else:
                        detected_files_disp = res.get("detected_filename") or ""

                    if USE_RICH:
                        table = Table(title=f"[{escape(item['name'])}] 웹 최신 릴리스 정보 (개발자 테스트)")
                        table.add_column("항목", style="cyan")
                        table.add_column("내용", style="green")
                        table.add_row("모드 이름", item["name"])
                        table.add_row("내장 제작자", creator_disp)
                        table.add_row("내부 식별 모드명", mod_title_disp)
                        table.add_row("웹 최신 버전", res.get("latest_version", "-"))
                        table.add_row("상태", up_text)
                        table.add_row("자동 다운로드 지원", auto_dl_label)
                        if detected_files_disp:
                            table.add_row("감지된 원격 파일", detected_files_disp)
                        if page_link:
                            table.add_row("배포 페이지 링크", page_link)
                        console.print(table)
                    else:
                        print(f"- 모드 이름: {item['name']}")
                        print(f"- 내장 제작자: {creator_disp}")
                        print(f"- 내부 식별 모드명: {mod_title_disp}")
                        print(f"- 웹 최신 버전: {res.get('latest_version', '-')}")
                        print(f"- 상태: {up_text}")
                        print(f"- 자동 다운로드 지원: {auto_dl_label}")
                        if detected_files_disp:
                            print(f"- 감지된 원격 파일: {detected_files_disp}")
                        if page_link:
                            print(f"- 배포 페이지 링크: {page_link}")

                    if res.get("is_early_access") or res.get("is_paid"):
                        if USE_RICH:
                            console.print(Panel(
                                "[bold yellow]🔒 선배포(얼리 액세스) / 멤버십 전용 배포 상태로 정상 감지되었습니다.[/bold yellow]\n"
                                f"[bold cyan]🔗 제작자 배포 페이지:[/bold cyan] [underline green]{escape(page_link)}[/underline green]",
                                title="[bold yellow]선배포 / 수동 다운로드 안내 확인[/bold yellow]",
                                border_style="yellow",
                            ))
                        else:
                            print("🔒 선배포(얼리 액세스) / 수동 다운로드 안내 상태로 정상 감지되었습니다.")

                    if sub_act == "2":
                        _run_dev_sandbox_download_test(item["name"], virtual_fn, res)
                    elif can_auto_download:
                        dl_q = input("\n🧪 임시 테스트 폴더에 실제 파일을 다운로드하여 압축해제까지 검증해보시겠습니까? (y/n) > ").strip().lower()
                        if dl_q == "y":
                            _run_dev_sandbox_download_test(item["name"], virtual_fn, res)
                    elif page_link:
                        open_q = input(f"\n🌐 배포 페이지({page_link})를 웹 브라우저로 열어보시겠습니까? (y/n) > ").strip().lower()
                        if open_q == "y":
                            import webbrowser
                            webbrowser.open(page_link)
                            print("✅ 웹 브라우저에서 배포 페이지가 열렸습니다.")
                break
            else:
                print("\n[!] 1, 2, 3, 4, 5 중 하나를 입력해 주세요.")

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
        print("4. 모드 업데이트 필요 여부 확인")
        print("5. 백업 목록 확인")
        print("6. Mods 폴더 경로 수동 변경")
        print("7. 모드 누락/매칭 진단 리포트 생성 (scan_report.txt)")
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
            if not check_update_needed_only(updater, scanner):
                print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
                break
            continue
        elif choice == "5":
            list_backups(backup_mgr)
        elif choice == "6":
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
        elif choice == "7":
            if not run_diagnostic_report_menu(updater, scanner):
                print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
                break
            continue
        elif choice in ["dev", "test"]:
            if not run_developer_catalog_test(updater):
                print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
                break
            continue
        elif choice in ["q", "exit"]:
            print("\n프로그램을 종료합니다. 즐거운 심즈 플레이 되세요!")
            break
        else:
            print("\n[!] 올바른 메뉴 번호를 입력해주세요.")

        input("\n계속하려면 Enter 키를 누르세요...")

if __name__ == "__main__":
    main()
