# gomobile köprüsü (libv2ray + go.Seq) yansıma ile çağrılır
-keep class go.** { *; }
-keep class libv2ray.** { *; }
-keepclasseswithmembernames class * { native <methods>; }
-repackageclasses ''
-allowaccessmodification

# 1.14: ekran (WebView) bilen köpri — usul atlary üýtgemesin
-keepattributes JavascriptInterface
-keepclassmembers class tm.yol.vpn.Main$Bridge { @android.webkit.JavascriptInterface <methods>; }
