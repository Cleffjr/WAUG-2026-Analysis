"""Matches transcribed from screenshots of data.allimediahub.com (Earlier results, 145 matches, 5-11 Oct 2026).
Row format: date|sport|category|stage|A name|A abbr|A score|B name|B abbr|B score|set/quarter scores|A pens|B pens
Team events leave the name blank (filled from the university abbreviation). Set scores are team A first."""
import pandas as pd
ABBR = {"OAU":"Obafemi Awolowo University","LCU":"Lead City University","UDS":"University for Development Studies",
 "UENR":"University of Energy and Natural Resources","ABUAD":"Afe Babalola University","NILE":"Nile University of Nigeria",
 "UNILESA":"University of Ilesa"}
RAW = """
2026-10-11|Football|Men|Final|||1|||1||5|4
2026-10-10|Football|Men|Third place|||0|||0||3|4
2026-10-10|Badminton|Mixed|Final|Leslie Ado / Kezia Amoah|UG|0|Oyinlola Sunday / Babatunde Dolapo|BIU|2|12-21 15-21||
2026-10-10|Badminton|Women|Final|Akoh Mary / Abdulkabir Khairat|UIL|2|Rowland Praise / Adewumi Barakat|OAU|0|21-10 21-3||
2026-10-10|Badminton|Men|Final|Leslie Ado / Andy Amofa|UG|1|Abraham Ayiteh / Reuben Tetteh|UCC|2|21-18 20-22 11-21||
2026-10-10|Badminton|Women|Final|Babatunde Dolapo|BIU|2|Angela Haruna|UNIABUJA|0|21-8 23-21||
2026-10-10|Badminton|Mixed|Semi-final|Samuel Martin / Angela Haruna|UNIABUJA|1|Oyinlola Sunday / Babatunde Dolapo|BIU|2|18-21 21-12 17-21||
2026-10-09|Badminton|Men|Final|Oyinlola Sunday|BIU|2|Andy Amofa|UG|0|21-15 21-14||
2026-10-09|Badminton|Women|Semi-final|Rowland Praise / Adewumi Barakat|OAU|2|Mimi Doo / Iorbee Faith|MOAUM|0|21-7 21-10||
2026-10-09|Badminton|Women|Semi-final|Stephanie Bequint / Kezia Amoah|UG|0|Akoh Mary / Abdulkabir Khairat|UIL|2|10-21 13-21||
2026-10-09|Volleyball|Men|Game 2|||3|||0|25-18 25-21 25-20||
2026-10-09|Badminton|Men|Semi-final|Akinbiola Paul / Akorede M.|OAU|0|Abraham Ayiteh / Reuben Tetteh|UCC|2|11-21 14-21||
2026-10-09|Badminton|Men|Semi-final|Leslie Ado / Andy Amofa|UG|2|Okunlola Israel / Yahaya Ayuba|UIL|0|21-8 21-15||
2026-10-09|Badminton|Mixed|Semi-final|Leslie Ado / Kezia Amoah|UG|2|Egbe Victor / Iorbee Faith|MOAUM|0|21-18 21-18||
2026-10-09|Volleyball|Women|Game 2|||3|||2|25-16 25-21 18-25 23-25 15-7||
2026-10-09|Badminton|Mixed|Quarter-final|Okunlola Israel / Akoh Mary|UIL|0|Samuel Martin / Angela Haruna|UNIABUJA|2|13-21 15-21||
2026-10-09|Badminton|Mixed|Quarter-final|Akorede M. / Rowland Praise|OAU|0|Egbe Victor / Iorbee Faith|MOAUM|2|19-21 22-24||
2026-10-09|Badminton|Men|Quarter-final|Lukman Abdulahi / Goodness E.|OAU|0|Okunlola Israel / Yahaya Ayuba|UIL|2|15-21 7-21||
2026-10-09|Tennis|Mixed|Final|Adisa Imole / Lagundoye Idowu|BIU|1|Nyamekye Samuel / Ankrah Aleona|UG|2|1-4 4-0 4-10||
2026-10-09|Badminton|Men|Round 1|Walimi Aliyu|UNILESA|2|Olaiwola Martin|OAU|0|21-17 21-13||
2026-10-09|Badminton|Women|Semi-final|Akoh Mary|UIL|0|Angela Haruna|UNIABUJA|2|12-21 10-21||
2026-10-09|Badminton|Men|Semi-final|Andy Amofa|UG|2|Reuben Tetteh|UCC|0|21-7 21-11||
2026-10-09|Badminton|Women|Semi-final|Kezia Amoah|UG|0|Babatunde Dolapo|BIU|2|4-21 6-21||
2026-10-09|Badminton|Men|Semi-final|Leslie Ado|UG|0|Oyinlola Sunday|BIU|2|9-21 6-21||
2026-10-09|Badminton|Men|Round 1|Okunlola Israel|UIL|0|Onasiwo Samuel|LASU|2|15-21 14-21||
2026-10-09|Badminton|Women|Quarter-final|Akoh Mary|UIL|2|Adewumi Barakat|OAU|0|21-5 21-7||
2026-10-09|Basketball|Men|Final|||66|||56|Q1 15-18 Q2 17-11 Q3 15-18 Q4 19-9||
2026-10-09|Badminton|Men|Round 1|Andy Amofa|UG|2|Samuel Martin|UNIABUJA|0|21-10 21-11||
2026-10-09|Badminton|Men|Round 1|Egbe Victor|MOAUM|0|Oyinlola Sunday|BIU|2|7-21 11-21||
2026-10-09|Tennis|Women|Final|Lagundoye Idowu|BIU|0|Ampah Tracy|KNUST|2|3-6 4-6||
2026-10-09|Badminton|Women|Quarter-final|Rowland Praise|OAU|0|Babatunde Dolapo|BIU|2|4-21 7-21||
2026-10-09|Badminton|Men|Round 1|Abraham Ayiteh|UCC|2|Akinbiola Paul|OAU|0|21-14 21-11||
2026-10-09|Badminton|Women|Quarter-final|Kezia Amoah|UG|2|Iorbee Faith|MOAUM|0|21-18 21-17||
2026-10-09|Tennis|Men|Final|Sani Musa|UNIABUJA|0|Nyamekye Samuel|UG|2|0-6 1-6||
2026-10-09|Badminton|Women|Preliminary|Stephanie Bequint|UG|0|Abdulkabir Kharat|UIL|2|18-21 11-21||
2026-10-09|Badminton|Men|Round 1|Lukman Abdulahi|OAU|0|Yahaya Ayuba|UIL|2|13-21 16-21||
2026-10-09|Basketball|Men|Third place|||90|||49|Q1 23-13 Q2 33-10 Q3 11-16 Q4 23-10||
2026-10-09|Badminton|Men|Quarter-final|Walimi Aliyu|UNILESA|0|Reuben Tetteh|UCC|2|10-21 8-21||
2026-10-09|Badminton|Men|Quarter-final|Andy Amofa|UG|2|Onasiwo Samuel|LASU|0|21-18 21-14||
2026-10-09|Badminton|Men|Quarter-final|Abraham Ayiteh|UCC|0|Oyinlola Sunday|BIU|2|15-21 17-21||
2026-10-09|Badminton|Men|Quarter-final|Leslie Ado|UG|2|Yahaya Ayuba|UIL|0|21-8 21-9||
2026-10-09|Badminton|Women|Quarter-final|Abdulkabir Kharat|UIL|0|Angela Haruna|UNIABUJA|2|9-21 9-21||
2026-10-08|Tennis|Women|Quarter-final|Lagundoye Idowu / Afolabi Imole|BIU|2|Animasaun Aderinsola / Oluchukwu Emmanuella|ABUAD|0|4-0 4-0||
2026-10-08|Table tennis|Men|Final|Boboye Samuel|BIU|4|Bright Udoh J.|BIU|0|11-6 11-9 12-10 11-7||
2026-10-08|Table tennis|Women|Final|Surmer Zainab|LASU|1|Hope Udoaka|BIU|4|9-11 11-9 4-11 5-11 7-11||
2026-10-08|Table tennis|Men|Final|Boboye Samuel / Adebowale A. Wilson|BIU|2|Matthew John / Bright Udoh J.|BIU|3|7-11 3-11 11-5 14-12 7-11||
2026-10-08|Tennis|Women|Quarter-final|Ampah Tracy / Adams Sekinat|KNUST|2|Ankrah Aleona / Atswei Rashidat|UG|0|4-0 4-0||
2026-10-08|Tennis|Men|Quarter-final|Oyelumade OluwaSeun / Wilson|UNIOSUN|0|Afini John-Paul / Iguodalo Desmond|OAU|2|0-4 0-4||
2026-10-08|Table tennis|Women|Final|Ayobami Taiwo / Olaifa Boluwatife|OAU|0|Surmer Zainab / Omotosho Ifeoluwa|LASU|3|5-11 5-11 4-11||
2026-10-08|Table tennis|Men|Final|Matthew John / Bright Udoh J.|BIU|3|Amu Omobolanle / Opefeyitimi Favour|OAU|0|11-7 11-6 11-9||
2026-10-08|Tennis|Women|Quarter-final|Bakare Abigael|UNIOSUN|0|Ankrah Aleona|UG|2|0-4 3-5||
2026-10-08|Tennis|Mixed|Round 1|Adisa Imole / Lagundoye Idowu|BIU|2|Afini John-Paul / Yinus Oyindamola|OAU|0|4-1 4-1||
2026-10-08|Tennis|Men|Quarter-final|Afini John-Paul / Iguodalo Desmond|OAU|0|Nyamekye Samuel / Glover Benjamin|UG|2|0-4 1-4||
2026-10-08|Tennis|Mixed|Round 1|Nyamekye Samuel / Ankrah Aleona|UG|2|Oyelumade OluwaSeun / Bakare Abigael|UNIOSUN|0|4-0 4-0||
2026-10-08|Tennis|Mixed|Round 1|Olamilekan Kareem / Oluchukwu Emmanuella|ABUAD|0|Afini John-Paul / Yinus Oyindamola|OAU|2|1-4 0-4||
2026-10-08|Basketball|Men|Game 8|||58|||80|Q1 15-28 Q2 16-17 Q3 13-16 Q4 14-19||
2026-10-08|Tennis|Men|Final|Adisa Imole / Akinmusire Michael|BIU|2|Nyamekye Samuel / Glover Benjamin|UG|0|4-0 4-2||
2026-10-08|Tennis|Women|Final|Lagundoye Idowu / Afolabi Imole|BIU|2|Ampah Tracy / Adams Sekinat|KNUST|0|4-2 4-2||
2026-10-08|Table tennis|Men|Semi-final|Boboye Samuel / Adebowale A. Wilson|BIU|3|Opadele Marvellous / Adeyemi Woduowo Olamilekan|OAU|0|11-5 11-4 11-1||
2026-10-08|Tennis|Men|Semi-final|Sani Musa|UNIABUJA|2|Glover Benjamin|UG|0|4-0 4-0||
2026-10-08|Tennis|Women|Semi-final|Afolabi Imole|BIU|0|Ampah Tracy|KNUST|2|1-4 2-4||
2026-10-08|Basketball|Men|Game 7|||74|||28|Q1 12-13 Q2 21-5 Q3 22-3 Q4 19-7||
2026-10-08|Football|Men|Semi-final|||1|||1||3|1
2026-10-08|Tennis|Women|Semi-final|Lagundoye Idowu|BIU|2|Ankrah Aleona|UG|0|4-1 4-0||
2026-10-08|Tennis|Men|Semi-final|Mohammed Mustapha|UNIABUJA|0|Nyamekye Samuel|UG|2|0-4 1-4||
2026-10-08|Football|Men|Semi-final|||0|||0||5|4
2026-10-07|Tennis|Men|Quarter-final|Aderibigbe Martins / Olamilekan Kareem|ABUAD|0|Adisa Imole / Akinmusire Michael|BIU|2|2-4 0-4||
2026-10-07|Football|Men|Group A|||0|||2||
2026-10-07|Volleyball|Men|Game 1|||3|||0|25-11 25-14 25-12||
2026-10-07|Basketball|Men|Game 6|||85|||25|Q1 21-6 Q2 18-9 Q3 19-5 Q4 27-5||
2026-10-07|Tennis|Women|Semi-final|Ampah Tracy / Adams Sekinat|KNUST|2|Ankrah Aleona / Atswei Rashidat|UG|0|4-0 4-0||
2026-10-07|Tennis|Men|Semi-final|Nyamekye Samuel / Glover Benjamin|UG|2|Afini John-Paul / Iguodalo Desmond|OAU|0|4-0 4-1||
2026-10-07|Volleyball|Women|Game 1|||3|||1|25-20 25-27 25-20 25-23||
2026-10-07|Tennis|Women|Semi-final|Lagundoye Idowu / Afolabi Imole|BIU|2|Animasaun Aderinsola / Oluchukwu Emmanuella|ABUAD|0|4-0 4-0||
2026-10-07|Tennis|Men|Semi-final|Aderibigbe Martins / Olamilekan Kareem|ABUAD|0|Adisa Imole / Akinmusire Michael|BIU|2|2-4 0-4||
2026-10-07|Table tennis|Men|Semi-final|Ezuba Peter Chiemeria|FUTA|3|Bright Udoh J.|BIU|4|11-7 8-11 13-15 11-6 13-11 8-11 8-11||
2026-10-07|Handball|Men|Match 1|||34|||12|1st 17-6 2nd 17-6||
2026-10-07|Tennis|Women|Round 1|Onoja Grace / Ormye Mimidi|MOAUM|0|Ankrah Aleona / Atswei Rashidat|UG|2|1-4 0-4||
2026-10-07|Tennis|Men|Round 1|Afini John-Paul / Iguodalo Desmond|OAU|2|Oyelumade OluwaSeun / Wilson|UNIOSUN|0|4-0 4-0||
2026-10-07|Table tennis|Women|Semi-final|Surmer Zainab|LASU|4|Omotosho Ifeoluwa|LASU|3|4-11 11-9 2-11 11-4 12-10 9-11 11-4||
2026-10-07|Table tennis|Women|Semi-final|Hope Udoaka|BIU|4|Ayobami Taiwo|OAU|0|11-5 11-3 11-5 14-12||
2026-10-07|Table tennis|Women|Quarter-final|Omotosho Ifeoluwa|LASU|4|Olaifa Boluwatife|OAU|0|11-4 11-6 11-3 11-3||
2026-10-07|Table tennis|Women|Quarter-final|Adefidipe Taiwo Adeola|FUTA|0|Ayobami Taiwo|OAU|4|3-11 5-11 4-11 3-11||
2026-10-07|Basketball|Women|Game 5|||69|||27|Q1 20-11 Q2 18-6 Q3 16-5 Q4 15-5||
2026-10-07|Tennis|Men|Round 1|Sani Musa / Mohammed Mustapha|UNIABUJA|0|Adisa Imole / Akinmusire Michael|BIU|2|2-4 2-4||
2026-10-07|Tennis|Women|Quarter-final|Atswei Rashidat|UG|0|Ampah Tracy|KNUST|2|0-4 1-4||
2026-10-07|Table tennis|Men|Quarter-final|Ezuba Peter Chiemeria|FUTA|4|Opadele Marvellous|OAU|0|11-5 11-6 11-5 11-8||
2026-10-07|Table tennis|Men|Quarter-final|Boboye Samuel|BIU|4|Surmer Qudus|LASU|0|11-8 11-6 11-9 11-6||
2026-10-07|Table tennis|Men|Quarter-final|Adebowale A. Wilson|BIU|4|Matthew John|BIU|3|6-11 17-15 6-11 11-7 11-13 11-8 11-6||
2026-10-07|Tennis|Women|Quarter-final|Ormye Mimidi|MOAUM|0|Afolabi Imole|BIU|2|0-4 0-4||
2026-10-07|Tennis|Men|Quarter-final|Nwiti Peter|OAU|0|Glover Benjamin|UG|2|0-4 0-4||
2026-10-07|Basketball|Men|Game 4|||53|||60|Q1 12-17 Q2 13-14 Q3 12-13 Q4 16-16||
2026-10-07|Tennis|Women|Quarter-final|Ankrah Aleona|UG|2|Bakare Abigael|UNIOSUN|0|4-1 5-3||
2026-10-07|Tennis|Men|Quarter-final|Olamilekan Kareem|ABUAD|0|Sani Musa|UNIABUJA|2|2-4 1-4||
2026-10-07|Table tennis|Men|Semi-final|Boboye Samuel|BIU|4|Adebowale A. Wilson|BIU|2|11-7 11-2 11-6 11-13 9-11 11-6||
2026-10-06|Tennis|Women|First round|Bakare Abigael|UNIOSUN|2|Onoja Grace|MOAUM|0|6-0 6-1||
2026-10-06|Tennis|Women|First round|Yinus Oyindamola|OAU|0|Atswei Rashidat|UG|2|4-6 0-6||
2026-10-06|Football|Men|Group A|||1|||0||
2026-10-06|Table tennis|Mixed|Final|Adebowale A. Wilson / Hope Udoaka|BIU|3|Surmer Qudus / Surmer Zainab|LASU|2|8-11 11-8 11-8 3-11 11-7||
2026-10-06|Table tennis|Mixed|Semi-final|Adebowale A. Wilson / Hope Udoaka|BIU|3|Akinduro Gabriel Tunde / Adefidipe Taiwo Adeola|FUTA|1|11-7 11-3 9-11 11-9||
2026-10-06|Table tennis|Mixed|Semi-final|Surmer Qudus / Surmer Zainab|LASU|3|Ayobami Taiwo / Amu Omobolanle|OAU|0|11-6 11-6 12-10||
2026-10-06|Table tennis|Mixed|Quarter-final|Ayobami Taiwo / Amu Omobolanle|OAU|3|Ezuba Peter Chiemeria / Ojo Rachael|FUTA|0|11-6 11-9 11-7||
2026-10-06|Tennis|Women|Quarter-final|Lagundoye Idowu|BIU|2|Adams Sekinat|KNUST|0|4-1 4-1||
2026-10-06|Table tennis|Mixed|Quarter-final|Adegboyega Oluwafunmilayo|OAU|0|Akinduro Gabriel Tunde|FUTA|3|2-11 7-11 4-11||
2026-10-06|Table tennis|Women|Group 3|Ayobami Taiwo|OAU|3|Ojo Rachael Omowunmi|FUTA|0|11-1 11-1 11-7||
2026-10-06|Table tennis|Women|Group 2|Adegboyega Oluwafunmilayo|OAU|1|Adefidipe Taiwo Adeola|FUTA|3|11-5 3-11 3-11 6-11||
2026-10-06|Table tennis|Women|Group 2|Surmer Zainab|LASU|3|Adegboyega Oluwafunmilayo|OAU|0|11-2 11-4 11-1||
2026-10-06|Table tennis|Women|Group 2|Surmer Zainab|LASU|3|Adefidipe Taiwo Adeola|FUTA|0|11-7 11-2 11-3||
2026-10-06|Table tennis|Women|Group 1|Olaifa Boluwatife|OAU|3|Ogidan Iyanuoluwa|OAU|0|11-8 11-9 11-7||
2026-10-06|Table tennis|Women|Group 1|Hope Udoaka|BIU|3|Olaifa Boluwatife|OAU|0|11-5 11-4 11-4||
2026-10-06|Basketball|Men|Game 3|||49|||58|Q1 20-14 Q2 11-14 Q3 6-16 Q4 12-14||
2026-10-06|Table tennis|Women|Group 3|Omotosho Ifeoluwa|LASU|3|Ojo Rachael Omowunmi|FUTA|0|11-2 11-6 11-1||
2026-10-06|Table tennis|Women|Group 3|Ayobami Taiwo|OAU|3|Omotosho Ifeoluwa|LASU|2|11-5 11-13 10-12 11-3 11-7||
2026-10-06|Table tennis|Women|Group 1|Hope Udoaka|BIU|3|Ogidan Iyanuoluwa|OAU|0|11-1 11-0 11-1||
2026-10-06|Tennis|Men|Quarter-final|Nyamekye Samuel|UG|2|Akinmusire Michael|BIU|0|4-1 5-4||
2026-10-06|Football|Men|Group B|||3|||0||
2026-10-06|Table tennis|Men|Group 1|Opadele Marvellous|OAU|3|Oyelami Stephen|FUATO|0|11-6 11-4 11-6||
2026-10-06|Table tennis|Men|Group 1|Boboye Samuel|BIU|3|Opadele Marvellous|OAU|0|11-2 11-2 11-3||
2026-10-06|Tennis|Men|Quarter-final|Aderibigbe Martins|ABUAD|0|Mohammed Mustapha|UNIABUJA|2|1-4 1-4||
2026-10-06|Table tennis|Men|Group 2|Opefeyitimi Favour|OAU|0|Bright Udoh J.|BIU|3|5-11 6-11 10-12||
2026-10-05|Table tennis|Men|Group 4|Matthew John|BIU|3|Adeyemi Woduowo Olamilekan|OAU|0|11-7 11-9 11-5||
2026-10-05|Table tennis|Men|Group 4|Akinduro Gabriel Tunde|FUTA|3|Ojo Owolabi|UNIABUJA|0|11-8 12-10 12-10||
2026-10-05|Table tennis|Men|Group 3|Adebowale A. Wilson|BIU|2|Ezuba Peter Chiemeria|FUTA|3|8-11 10-12 12-10 11-7 8-11||
2026-10-05|Table tennis|Men|Group 3|Amu Omobolanle|OAU|3|Ayomide Adeleke|UNILESA|0|11-5 11-2 11-1||
2026-10-05|Table tennis|Men|Group 4|Adeyemi Woduowo Olamilekan|OAU|0|Ojo Owolabi|UNIABUJA|3|7-11 2-11 8-11||
2026-10-05|Table tennis|Men|Group 2|Surmer Qudus|LASU|3|Opefeyitimi Favour|OAU|0|11-3 11-6 12-10||
2026-10-05|Table tennis|Men|Group 4|Akinduro Gabriel Tunde|FUTA|0|Matthew John|BIU|3|2-11 3-11 6-11||
2026-10-05|Table tennis|Men|Group 3|Ezuba Peter Chiemeria|FUTA|3|Ayomide Adeleke|UNILESA|0|11-3 11-3 11-6||
2026-10-05|Table tennis|Men|Group 3|Amu Omobolanle|OAU|0|Adebowale A. Wilson|BIU|3|8-11 8-11 3-11||
2026-10-05|Table tennis|Men|Group 4|Matthew John|BIU|2|Ojo Owolabi|UNIABUJA|3|7-11 5-11 11-6 12-10 5-11||
2026-10-05|Table tennis|Men|Group 1|Boboye Samuel|BIU|3|Oyelami Stephen|FUATO|0|11-2 11-1 11-4||
2026-10-05|Basketball|Men|Game 2|||41|||59|Q1 12-18 Q2 9-16 Q3 6-12 Q4 14-13||
2026-10-05|Table tennis|Men|Group 3|Adebowale A. Wilson|BIU|3|Ayomide Adeleke|UNILESA|0|11-4 11-5 11-1||
2026-10-05|Table tennis|Men|Group 4|Akinduro Gabriel Tunde|FUTA|3|Adeyemi Woduowo Olamilekan|OAU|0|11-2 11-2 11-4||
2026-10-05|Table tennis|Men|Group 2|Surmer Qudus|LASU|2|Bright Udoh J.|BIU|3|4-11 11-4 12-10 3-11 9-11||
2026-10-05|Table tennis|Men|Group 3|Amu Omobolanle|OAU|0|Ezuba Peter Chiemeria|FUTA|3|5-11 6-11 7-11||
2026-10-05|Basketball|Women|Game 1|||29|||73|Q1 10-20 Q2 5-17 Q3 10-22 Q4 4-14||
2026-10-05|Tennis|Men|Round 1|Nwiti Peter|OAU|2|Oyelumade OluwaSeun|UNIOSUN|0|6-0 7-6||
2026-10-05|Tennis|Men|Round 1|Adisa Imole|BIU|0|Sani Musa|UNIABUJA|2|5-7 5-7||
2026-10-05|Tennis|Men|Round 1|Olamilekan Kareem|ABUAD|2|Wilson Christian|UNIOSUN|0|6-0 6-2||
2026-10-05|Tennis|Women|Round 1|Ormye Mimidi|MOAUM|2|Oluchukwu Emmanuella|ABUAD|0|6-1 6-0||
2026-10-05|Tennis|Men|Round 1|Asantu Amos|UCC|1|Akinmusire Michael|BIU|2|6-4 0-6 2-6||
2026-10-05|Football|Men|Group A|||4|||2||
2026-10-05|Tennis|Women|Round 1|Animasaun Aderinsola|ABUAD|0|Adams Sekinat|KNUST|2|0-6 0-6||
2026-10-05|Tennis|Men|Round 1|Mohammed Mustapha|UNIABUJA|2|Afini John-Paul|OAU|0|6-3 6-2||
"""
# Team-event pairings (A abbr, B abbr) in row order for rows with blank names
TEAM = iter([("OAU","LCU"),("UDS","UENR"),("OAU","ABUAD"),("OAU","ABUAD"),("NILE","LCU"),("ABUAD","OAU"),("ABUAD","NILE"),
 ("LCU","OAU"),("LCU","UENR"),("OAU","UDS"),("ABUAD","LCU"),("OAU","ABUAD"),("NILE","OAU"),("OAU","ABUAD"),("OAU","UNILESA"),
 ("OAU","ABUAD"),("ABUAD","LCU"),("LCU","UDS"),("LCU","NILE"),("OAU","UENR"),("OAU","ABUAD"),("ABUAD","OAU"),("UDS","ABUAD")])

rows = []
for line in RAW.strip().split("\n"):
    f = line.split("|"); f += [""] * (13 - len(f))
    d, sport, cat, stage, an, aa, sa, bn, ba, sb, sets, pa, pb = f
    if not an:
        aa, ba = next(TEAM); an, bn = ABBR[aa], ABBR[ba]
    rows.append(dict(date=d, sport=sport, category=cat, stage=stage, team_a=an, uni_a=aa, score_a=int(sa),
                     team_b=bn, uni_b=ba, score_b=int(sb), sets=sets, pens_a=pa, pens_b=pb))
m = pd.DataFrame(rows)
m["pens_a"] = pd.to_numeric(m.pens_a); m["pens_b"] = pd.to_numeric(m.pens_b)
pen = m.pens_a.notna()
m["winner"] = "A"
m.loc[(m.score_a < m.score_b) | (pen & (m.pens_a < m.pens_b)), "winner"] = "B"
# sanity checks
assert next(TEAM, None) is None
assert (m[~pen].score_a != m[~pen].score_b).all()
import re
for _, r in m.iterrows():
    if r.sport == "Basketball":
        q = [tuple(map(int, x.split("-"))) for x in re.findall(r"\d+-\d+", r.sets)]
        assert sum(a for a, _ in q) == r.score_a and sum(b for _, b in q) == r.score_b, r.to_dict()
    elif r.sport in ("Badminton", "Table tennis", "Tennis", "Volleyball"):
        q = [tuple(map(int, x.split("-"))) for x in r.sets.split()]
        assert sum(a > b for a, b in q) == r.score_a and sum(b > a for a, b in q) == r.score_b, r.to_dict()
m.to_csv("data/matches.csv", index=False)
print(len(m), "matches", m.date.min(), "to", m.date.max())
