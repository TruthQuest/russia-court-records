#!/usr/bin/env python3
"""Build synthetic OVD rows, court pages and a sanctions file for an offline end-to-end test.
All people and judges here are invented."""
import csv
import json
import pathlib

D = pathlib.Path(__file__).parent / "fixtures"
D.mkdir(exist_ok=True)

COLS = ["Record ID", "ID фигуранта", "Name (first name, last name)", "Region", "ISO код региона", "City",
        "Статья без части", "Article of the Criminal Code", "Дата приговора", "Дата первого приговора",
        "Дата начала преследования", "Номер дела", "Criminal case name", "Story", "Plot of the case",
        "Hearings with sentence", "Persecuted person state within the case"]
rows = [
    ["recA", "p1", "Svetlana Petrova", "Sverdlovsk Oblast", "RU-SVE", "Nizhny Tagil", "284.1", "", "4/22/2026 15:00",
     "4/22/2026 12:00", "1/10/2025", "1-913/2025", "Test case A",
     "On 22 April the Tagilstroevsky District Court of Nizhny Tagil sentenced her.", "", "", ""],
    ["recB", "p2", "Ruslan Abasov", "Moscow", "RU-MOW", "Moscow", "213, 214", "", "", "", "3/1/2022",
     "01-0123/2023 (01-0456/2022)", "Test case B", "", "", "", ""],
    ["recC", "p3", "Shahban Abakargadzhiev", "Dagestan", "RU-DA", "Khasavyurt", "207.3", "", "5/27/2024 12:00",
     "11/8/2023 08:00", "3/1/2023", "1-485/2023", "Test case C", "", "", "", ""],
    ["recD", "p4", "Ivan Sidorov", "Rostov Oblast", "RU-ROS", "Rostov-on-Don", "205.2", "", "3/10/2025 10:00",
     "", "2/1/2024", "", "Test case D", "", "", "", ""],
]
with open(D / "ovd.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(COLS)
    w.writerows(rows)


def page(body: str) -> str:
    return f'<html><head><meta charset="windows-1251"></head><body>{body}</body></html>'


def results(rows_html: str) -> str:
    return page("<table><tr><th>№ дела</th><th>Дата поступления</th><th>Информация по делу</th><th>Судья</th>"
                "<th>Дата решения</th><th>Решение</th><th>Судебные акты</th></tr>" + rows_html + "</table>")


def cp(name: str, html: str) -> None:
    (D / name).write_bytes(html.encode("cp1251"))


cp("dir_66.html", page(
    '<ul><li><a href="http://tagilstroevsky--svd.sudrf.ru">Тагилстроевский районный суд г. Нижнего Тагила</a></li>'
    '<li><a href="http://leninsky--ekb.sudrf.ru">Ленинский районный суд г. Екатеринбурга</a></li>'
    '<li><a href="http://oblsud--svd.sudrf.ru">Свердловский областной суд</a></li>'
    '<li><a href="http://mirsud.sudrf.ru">Мировой судья участка 1</a></li></ul>'))
cp("dir_05.html", page(
    '<a href="http://xasavjurtovskij-gs--dag.sudrf.ru">Хасавюртовский городской суд Республики Дагестан</a>'
    '<a href="http://vs--dag.sudrf.ru">Верховный суд Республики Дагестан</a>'))
cp("dir_61.html", page(
    '<a href="http://kirovsky--ros.sudrf.ru">Кировский районный суд г. Ростова-на-Дону</a>'
    '<a href="http://oblsud--ros.sudrf.ru">Ростовский областной суд</a>'
    '<a href="http://yovs--ros.sudrf.ru">Южный окружной военный суд</a>'))
cp("dir_77.html", page('<a href="http://mgs--msk.sudrf.ru">Московский городской суд</a>'))
cp("form.html", page(
    '<form action="/modules.php" method="get">'
    '<input type="hidden" name="name" value="sud_delo"><input type="hidden" name="srv_num" value="1">'
    '<input type="hidden" name="name_op" value="r"><input type="hidden" name="delo_id" value="1540006">'
    '<input type="hidden" name="case_type" value="0"><input type="hidden" name="new" value="0">'
    '<input type="hidden" name="delo_table" value="u1_case">'
    '<label for="n">Номер дела</label><input id="n" type="text" name="U1_CASE__CASE_NUMBERSS">'
    '<label for="f">ФИО</label><input id="f" type="text" name="U1_DEFENDANT__NAMESS"></form>'))
cp("form_captcha.html", page(
    '<div id="content"><table><form action="/modules.php" method="get">'
    '<input type="hidden" name="captchaid" value="CID42">'
    '<img src="data:image/png;base64,iVBORw0KGgo=">'
    '<label>Проверочный код</label><input type="text" name="captcha"></form></table></div>'))
cp("res_tagil.html", results(
    '<tr><td><a href="/modules.php?name=sud_delo&srv_num=1&name_op=case&case_id=111&delo_id=1540006">1-913/2025</a></td>'
    '<td>01.12.2025</td><td>ПЕТРОВА С.А. - ст.284.1 ч.2 УК РФ</td><td>Иванов Иван Иванович</td>'
    '<td>22.04.2026</td><td>Вынесен ПРИГОВОР</td><td></td></tr>'))
cp("res_tagil_p1.html", page(
    '<p>Всего по запросу найдено — 2</p>'
    '<table><tr><th>№ дела</th><th>Дата поступления</th><th>Информация по делу</th><th>Судья</th>'
    '<th>Дата решения</th><th>Решение</th><th>Судебные акты</th></tr>'
    '<tr><td><a href="/modules.php?name=sud_delo&name_op=case&case_id=110&delo_id=1540006">1-700/2025</a></td>'
    '<td>01.11.2025</td><td>СМИРНОВ А.А. - ст.284.1 ч.1 УК РФ</td><td>Иванов Иван Иванович</td>'
    '<td>01.03.2026</td><td>Вынесен ПРИГОВОР</td><td></td></tr></table>'
    '<a href="/modules.php?name=sud_delo&srv_num=1&name_op=r&page=2&delo_id=1540006">2</a>'))
cp("res_tagil_p2.html", results(
    '<tr><td><a href="/modules.php?name=sud_delo&srv_num=1&name_op=case&case_id=111&delo_id=1540006">1-913/2025</a></td>'
    '<td>01.12.2025</td><td>ПЕТРОВА С.А. - ст.284.1 ч.2 УК РФ</td><td>Иванов Иван Иванович</td>'
    '<td>22.04.2026</td><td>Вынесен ПРИГОВОР</td><td></td></tr>'))
cp("res_khas.html", results(
    '<tr><td><a href="/modules.php?name=sud_delo&name_op=case&case_id=222&delo_id=1540006">1-485/2023</a></td>'
    '<td>01.09.2023</td><td>МАГОМЕДОВ М.М. - ст.158 ч.2 УК РФ</td><td>Алиев А.А.</td>'
    '<td>08.11.2023</td><td>Вынесен ПРИГОВОР</td><td></td></tr>'))
cp("res_yovs.html", results(
    '<tr><td><a href="/modules.php?name=sud_delo&name_op=case&case_id=333&delo_id=1540006">2-15/2025</a></td>'
    '<td>10.01.2025</td><td>СИДОРОВ И.П. - ст.205.2 ч.2 УК РФ</td><td>Петров П.П.</td>'
    '<td>10.03.2025</td><td>Вынесен ПРИГОВОР</td><td></td></tr>'))
cp("res_empty.html", page("<p>Данных по запросу не обнаружено</p>"))
cp("card_tagil.html", page(
    '<table><tr><td colspan="2">ДЕЛО</td></tr>'
    '<tr><td>Уникальный идентификатор дела</td><td>66RS0009-01-2025-004567-12</td></tr>'
    '<tr><td>Номер дела</td><td>1-913/2025</td></tr>'
    '<tr><td>Судья</td><td>Иванов Иван Иванович</td></tr>'
    '<tr><td>Дата рассмотрения</td><td>22.04.2026</td></tr>'
    '<tr><td>Результат рассмотрения</td><td>Вынесен ПРИГОВОР</td></tr></table>'
    '<table><tr><td colspan="4">ДВИЖЕНИЕ ДЕЛА</td></tr>'
    '<tr><th>Наименование события</th><th>Дата</th><th>Время</th><th>Результат события</th></tr>'
    '<tr><td>Судебное заседание</td><td>22.04.2026</td><td>10:00</td><td>Вынесен приговор</td></tr></table>'
    '<a href="http://oblsud--svd.sudrf.ru/modules.php?name=sud_delo&name_op=case&case_id=999&delo_id=4">Апелляция</a>'))
cp("card_appeal.html", page(
    '<table><tr><td>Номер дела</td><td>22-555/2026</td></tr><tr><td>Судья-докладчик</td><td>Кузнецова Е.В.</td></tr>'
    '<tr><td>Дата рассмотрения</td><td>01.07.2026</td></tr></table>'))
cp("card_yovs.html", page('<table><tr><td>Номер дела</td><td>2-15/2025</td></tr><tr><td>Судья</td><td>Петров П.П.</td></tr></table>'))
(D / "mgs_results.html").write_text(
    '<html><body><table><tr><th>Номер дела</th><th>Стороны</th><th>Текущее состояние</th><th>Судья</th><th>Статья</th></tr>'
    '<tr><td><a href="/rs/meshchanskij/services/cases/criminal/details/abc-123">01-0123/2023</a></td>'
    '<td>Обвиняемый: Абасов Р.Т.</td><td>Вступило в силу</td><td>Сидорова А.В.</td><td>213</td></tr></table></body></html>',
    "utf-8")
(D / "mgs_card.html").write_text(
    '<html><body><div class="row_card"><div class="left">Номер дела</div><div class="right">01-0123/2023</div></div>'
    '<div class="row_card"><div class="left">Судья</div><div class="right">Сидорова Анна Викторовна</div></div>'
    '<div class="row_card"><div class="left">Уникальный идентификатор дела</div><div class="right">77RS0016-01-2022-012345-67</div></div>'
    '</body></html>', "utf-8")

courts_json = {
    "66": [{"court_id": "66RS0009", "court_name": "Тагилстроевский районный суд г. Нижнего Тагила (Свердловская область)",
            "court_website": "http://tagilstroevsky--svd.sudrf.ru", "srv": ["1"]},
           {"court_id": "66RS0062", "court_name": "Ленинский районный суд г. Екатеринбурга (Свердловская область)",
            "court_website": "http://leninsky--ekb.sudrf.ru", "srv": ["1"]},
           {"court_id": "66OS0000", "court_name": "Свердловский областной суд (Свердловская область)",
            "court_website": "http://oblsud--svd.sudrf.ru", "srv": ["1"]}],
    "05": [{"court_id": "05RS0046", "court_name": "Хасавюртовский городской суд Республики Дагестан (Республика Дагестан)",
            "court_website": "http://xasavjurtovskij-gs--dag.sudrf.ru", "srv": ["1", "2"]},
           {"court_id": "05OS0000", "court_name": "Верховный суд Республики Дагестан (Республика Дагестан)",
            "court_website": "http://vs--dag.sudrf.ru", "srv": ["1"]}],
    "61": [{"court_id": "61RS0003", "court_name": "Кировский районный суд г. Ростова-на-Дону (Ростовская область)",
            "court_website": "http://kirovsky--ros.sudrf.ru", "srv": ["1"]},
           {"court_id": "61OS0000", "court_name": "Ростовский областной суд (Ростовская область)",
            "court_website": "http://oblsud--ros.sudrf.ru", "srv": ["1"]},
           {"court_id": "61OV0000", "court_name": "Южный окружной военный суд (Ростовская область)",
            "court_website": "http://yovs--ros.sudrf.ru", "srv": ["1"]}],
    "77": [{"court_id": "77OS0000", "court_name": "Московский городской суд (Город Москва)",
            "court_website": "http://mgs--msk.sudrf.ru", "srv": ["1"]}],
}
(D / "courts.json").write_text(json.dumps(courts_json, ensure_ascii=False), "utf-8")

fmap = [
    [r"sudrf\.ru/index\.php.*court_subj=66", "dir_66.html", "cp1251"],
    [r"sudrf\.ru/index\.php.*court_subj=05", "dir_05.html", "cp1251"],
    [r"sudrf\.ru/index\.php.*court_subj=61", "dir_61.html", "cp1251"],
    [r"sudrf\.ru/index\.php.*court_subj=77", "dir_77.html", "cp1251"],
    [r"xasavjurtovskij.*name_op=sf", "form_captcha.html", "cp1251"],
    [r"name_op=sf", "form.html", "cp1251"],
    [r"tagilstroevsky--svd.*name_op=case", "card_tagil.html", "cp1251"],
    [r"oblsud--svd.*name_op=case", "card_appeal.html", "cp1251"],
    [r"yovs--ros.*name_op=case", "card_yovs.html", "cp1251"],
    [r"tagilstroevsky--svd.*CASE_NUMBERSS=1-913", "res_tagil.html", "cp1251"],
    [r"tagilstroevsky--svd.*name_op=r.*page=2", "res_tagil_p2.html", "cp1251"],
    [r"tagilstroevsky--svd.*LAW_ARTICLESS=284\.1.*ENTRY_DATE1D=01\.01\.2025", "res_tagil_p1.html", "cp1251"],
    [r"xasavjurtovskij.*LAW_ARTICLESS=207\.3.*captcha=1234", "res_khas.html", "cp1251"],
    [r"xasavjurtovskij.*CASE_NUMBERSS=1-485.*captcha=1234", "res_khas.html", "cp1251"],
    [r"yovs--ros.*NAMESS=%D1%E8%E4%EE%F0%EE%E2", "res_yovs.html", "cp1251"],
    [r"mos-gorsud\.ru/rs/.*/details/", "mgs_card.html", "utf-8"],
    [r"mos-gorsud\.ru/search", "mgs_results.html", "utf-8"],
    [r"modules\.php", "res_empty.html", "cp1251"],
]
(D / "fixture_map.json").write_text(json.dumps(fmap, ensure_ascii=False, indent=1), "utf-8")

with open(D / "targets.simple.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "schema", "name", "aliases", "birth_date", "countries", "addresses", "identifiers",
                "sanctions", "phones", "emails", "dataset", "first_seen", "last_seen", "last_change"])
    w.writerow(["NK-test1", "Person", "Ivan Ivanovich IVANOV", "Иванов Иван Иванович", "1970-01-01", "ru", "", "",
                "Test programme: judge of a district court", "", "", "Test list", "", "", ""])
    w.writerow(["NK-test2", "Person", "IVANOV, Igor Petrovich", "", "", "ru", "", "", "Test programme", "", "",
                "Test list", "", "", ""])
    w.writerow(["NK-test3", "Person", "Anna Viktorovna Sidorova", "", "", "ru", "", "", "Test programme", "", "",
                "Test list", "", "", ""])
print("fixtures written to", D)
