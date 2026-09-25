#Persistent
SetTimer, CheckAndClick, 3000 ; ہر 3 سیکنڈ بعد اسکرین چیک کرے گا

CheckAndClick:
    ; اسکرین پر چیک باکس کی تصویر ڈھونڈو
    ; *50 کا مطلب ہے کہ تھوڑا سا فرق ہو تو بھی پکڑ لے گا
    ImageSearch, FoundX, FoundY, 0, 0, A_ScreenWidth, A_ScreenHeight, *50 cf_checkbox.png
    
    if (ErrorLevel = 0) {
        ; اگر مل گیا تو ماؤس کو وہاں لے جاؤ اور کلک کرو
        MouseMove, %FoundX%, %FoundY%
        Sleep, 300
        Click, %FoundX%, %FoundY%
        Sleep, 5000 ; کلک کے بعد 5 سیکنڈ رکو
    }
return
